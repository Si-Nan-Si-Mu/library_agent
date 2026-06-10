import json
import logging
import os
import re
from typing import Any, Text, Dict, List, Optional, Tuple

try:
    from kg_module.env_bootstrap import load_repo_dotenv

    load_repo_dotenv()
except Exception:
    pass

from .neo4j_library_store import (
    borrow_book,
    catalog_search_by_topic,
    format_on_shelf_borrow_preview,
    get_active_borrow_count,
    get_library_book_by_call_number,
    get_library_collection_stats,
    list_on_shelf_overview_page,
    search_library_books_for_intro,
    list_active_borrow_records,
    list_catalog_books,
    list_borrow_records,
    list_borrowed_by_title,
    list_on_shelf_by_title,
    lookup_circulation,
    record_borrow_transaction,
    return_book,
)

from rasa_sdk import Action, Tracker  # type: ignore[reportMissingImports]
from rasa_sdk.events import SlotSet, AllSlotsReset, ActiveLoop, FollowupAction  # type: ignore[reportMissingImports]
from rasa_sdk.forms import FormValidationAction  # type: ignore[reportMissingImports]

try:
    from rasa_sdk.executor import CollectingDispatcher  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover - fallback for IDE/static analysis env
    CollectingDispatcher = Any

from .deepseek_client import deepseek_chat
from .reading_web_search import build_reading_web_context
from .intent_coverage import (
    borrow_policy_anchor,
    build_deepseek_user_payload,
    nlu_intent_signals,
    score_kb_entries,
    should_treat_as_compound_fallback,
)
from .graph_rag import graph_rag_enabled, graph_rag_retrieve_evidence
from .neo4j_graph import recommend_books_by_topic as neo4j_recommend_by_topic

_DATA_INQUIRY_SYSTEM = (
    "你是高校图书馆智能助手（演示环境）。用户会做开放数据、统计口径、借阅趋势类、推荐阅读等类别的提问。"
    "你只提供一般性方法、概念说明与合规注意点；不得编造具体的借阅量、百分比、排名等数字。"
    "若需要精确数据，应引导对方通过馆方 OPAC、报表系统或经授权的统计服务查询，并提及权限与审计要求。"
    "当提示词中附有「Neo4j 图谱检索结果」JSON 事实时，应优先根据其回答书名、作者、主题、类目、馆藏状态等结构化问题，不要捏造未出现于该 JSON 的记录。"
    "未附图谱片段时，仍可结合书目常识作答，但不要编造即时 OPAC；涉及办理借还仅引导用户使用本对话的借书/还书表单。"
    "回答使用用户相对熟悉的语言，条理清晰，篇幅适中。"
    "不要使用任何括号表示情绪或动作。"
)


def _circulation_label(row: Dict[str, Any]) -> str:
    return "在架可借" if int(row.get("is_borrow") or 0) == 0 else "已借出"


def _match_catalog_title(catalog_rows: List[dict], graph_title: str) -> Optional[dict]:
    gt = (graph_title or "").strip()
    if not gt:
        return None
    for r in catalog_rows:
        lb = str(r.get("lib_book") or "").strip()
        if not lb:
            continue
        if gt == lb or gt in lb or lb in gt:
            return r
    return None


def _catalog_book_key_set(catalog_rows: List[dict]) -> set:
    out: set = set()
    for r in catalog_rows or []:
        k = str(r.get("book_key") or "").strip().upper()
        if k:
            out.add(k)
    return out


def _graph_row_in_catalog(gr: dict, catalog_rows: List[dict], key_set: Optional[set] = None) -> bool:
    """图谱节点是否已属于主题检索命中的馆藏行（避免与在架/已借表重复展示）。"""
    ks = key_set if key_set is not None else _catalog_book_key_set(catalog_rows)
    gk = str(gr.get("book_key") or "").strip().upper()
    if gk and gk in ks:
        return True
    title = (gr.get("title") or "").strip()
    if title and _match_catalog_title(catalog_rows, title):
        return True
    return False


_READING_DEEPSEEK_SYSTEM = (
    "你是高校图书馆「阅读推广」助手，语气亲切、有分享感。"
    "下列【馆内检索事实】JSON 来自演示图数据库：索书号、是否在架以其中字段为准，不得虚构或改写。"
    "若另有【网络参考】，仅为开放网页摘要线索，须与馆内事实区分，勿把网络内容说成本馆已定藏。"
    "请用中文输出 400～800 字：① 一两句点题；② 结合馆内事实与（若有）网络参考，各用 1～3 处线索展开，"
    "对重点书目各给一句适合转发的「内容简介式」短句或阅读感受；③ 结尾提醒读者「是否可借、索书号以聊天下方表格为准」。"
    "不要使用括号表情，不要复述整段 JSON。"
    "正文必须使用 Markdown 排版：至少包含 **加粗**（如书名）与 `##` 小标题或 `-` 无序列表之一，可以附带其他 Markdown 语法，如`[链接](https://example.com)`、色彩、彩字、斜体等。"
    "避免整段只有纯文字；可用 `## 导读`、`## 在架选读` 等分节。"
)

_READING_OFFCATALOG_SYSTEM = (
    "你是高校图书馆阅读推广编辑。用户关心某一阅读主题，下列「本馆演示库已有书目」仅作去重参考，"
    "你推荐的条目**不得**与其中任一书名相同或仅为同一书的不同副标题写法。\n"
    "请只输出一个 JSON 数组（不要 Markdown、不要代码围栏外的说明）；数组每项形如 "
    '{"title":"书名（中译名即可）","note":"100～200 字适读说明"} ，'
    "推荐 4～8 本该主题下**常见经典或口碑作品**，可为馆内未收录的著作；勿写索书号、勿声称已在演示库上架。"
)


def _entity_text(e: Dict[str, Any]) -> str:
    v = e.get("value")
    if isinstance(v, str) and v.strip():
        return v.strip()
    t = e.get("text")
    if isinstance(t, str) and t.strip():
        return t.strip()
    return ""


def _longest_topic_author_entity(tracker: Tracker, text: str) -> str:
    """从 NLU 实体中取 topic/author 的最长片段（优先 start/end，避免「日本文学」被标成短词「文学」）。"""
    best = ""
    best_len = 0
    full = text or ""
    for e in tracker.latest_message.get("entities") or []:
        if not isinstance(e, dict):
            continue
        en = str(e.get("entity") or "")
        if en not in ("topic", "author"):
            continue
        start, end = e.get("start"), e.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(full):
            span = full[start:end].strip()
        else:
            span = _entity_text(e)
        if len(span) > best_len:
            best, best_len = span, len(span)
    return best


def _expand_topic_suffix(utterance: str, entity_topic: str) -> str:
    """当实体仅为「文学」等后缀而整句含「日本文学」时，扩展为更长主题词。"""
    et = (entity_topic or "").strip()
    if len(et) < 2:
        return et
    u = (utterance or "").strip()
    if not u or et not in u:
        return et
    pat = re.compile(rf"[\u4e00-\u9fa5]{{0,12}}{re.escape(et)}")
    best = et
    for m in pat.finditer(u):
        w = m.group(0).strip()
        if 2 <= len(w) <= 24 and len(w) > len(best):
            best = w
    return best


def _prefer_richer_topic(a: str, b: str) -> str:
    """在弱解析与实体解析之间取信息更完整的一个（更长或包含另一方）。"""
    a, b = (a or "").strip(), (b or "").strip()
    if not a:
        return b
    if not b:
        return a
    if a == b:
        return a
    if a in b and len(b) > len(a):
        return b
    if b in a and len(a) > len(b):
        return a
    return b if len(b) > len(a) else a


def _weak_topic_from_utterance(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    vague = {
        "推荐阅读",
        "推荐几本书",
        "推荐",
        "有没有推荐的书籍",
        "不知道借什么随便看看",
    }
    if s in vague:
        return ""
    for p in (
        "推荐阅读",
        "推荐一下",
        "给我推荐",
        "帮我推荐",
        "请推荐",
        "推荐点",
        "推荐些",
        "推荐几本",
        "推荐",
        "有没有关于",
        "关于",
        "想读点",
        "想看点",
        "想看",
        "来点",
        "想找",
        "求推荐",
        "求安利",
        "安利",
        "按主题",
        "按",
    ):
        if s.startswith(p):
            s = s[len(p) :].lstrip(" ，。、；:：的")
    s = re.sub(r"(的书|书籍|图书|书单|方面|领域|方向)$", "", s).strip()
    if len(s) > 48:
        s = s[:48].rstrip(" ，。、") + "…"
    return s


def _resolve_reading_topic(tracker: Tracker) -> str:
    """优先本轮用户话中的实体/弱解析，再回退槽位，减轻「日本文学」→「文学」与旧槽位串线。"""
    text = (tracker.latest_message.get("text") or "").strip()
    ent = _longest_topic_author_entity(tracker, text)
    if ent:
        ent = _expand_topic_suffix(text, ent)
    weak = _weak_topic_from_utterance(text)
    merged = _prefer_richer_topic(ent, weak)
    if merged:
        return merged[:80].strip()
    author_slot = (tracker.get_slot("author") or "").strip()
    topic_slot = (tracker.get_slot("topic") or "").strip()
    if topic_slot:
        return _expand_topic_suffix(text, topic_slot)[:80].strip()
    if author_slot:
        return author_slot[:80].strip()
    return ""


def _reading_facts_dict(catalog_rows: List[dict], graph_rows: List[dict]) -> Dict[str, Any]:
    def cr(r: dict) -> Dict[str, Any]:
        return {
            "title": (str(r.get("lib_book") or "")).strip(),
            "call_number": (str(r.get("book_key") or "")).strip(),
            "on_shelf": int(r.get("is_borrow") or 0) == 0,
            "book_pos": (str(r.get("book_pos") or "").strip() or None),
            "summary": (str(r.get("summary") or "").strip()[:200] or None),
        }

    def gr(r: dict) -> Dict[str, Any]:
        return {
            "title": (str(r.get("title") or "")).strip(),
            "call_number": (str(r.get("book_key") or "")).strip() or None,
            "rating": r.get("rating"),
            "authors": r.get("authors") if isinstance(r.get("authors"), list) else [],
            "disciplines": r.get("disciplines")
            if isinstance(r.get("disciplines"), list)
            else [],
            "related_authors": r.get("related_authors")
            if isinstance(r.get("related_authors"), list)
            else [],
            "summary": (str(r.get("summary") or "")).strip()[:200] or None,
        }

    on_shelf = [cr(r) for r in catalog_rows if int(r.get("is_borrow") or 0) == 0][:14]
    borrowed = [cr(r) for r in catalog_rows if int(r.get("is_borrow") or 0) == 1][:8]
    graph = [gr(r) for r in graph_rows[:10]]
    return {"on_shelf": on_shelf, "borrowed": borrowed, "graph": graph}


_GRAPH_INTRO_DEEPSEEK_SYSTEM = (
    "你是高校图书馆荐书编辑。用户给定检索主题与若干本候选书（来自知识图谱，字段含 book_key、题名、作者、评分、已有简介片段）。"
    "请为每本书写一条「扩展推荐」表格用的简介：50～100 字中文，语气可分享；可适度使用 Markdown（如 **加粗** 强调书名或概念）。"
    "须紧扣输入中的事实，勿编造索书号；若某书信息极少，可写阅读角度或适读人群。"
    '只输出一个 JSON 数组，不要其它说明文字；数组元素形如 {"book_key":"KG.GR.00001","intro":"……"} ，'
    "其中 book_key 必须与输入中的 book_key 完全一致。"
)


def _extract_first_json_array(text: str) -> Optional[Any]:
    s = (text or "").strip()
    if not s:
        return None
    for token in ("```json", "```JSON", "```"):
        if token in s:
            i = s.find(token)
            j = s.find("```", i + len(token))
            if j > i:
                s = s[i + len(token) : j].strip()
            break
    lb = s.find("[")
    rb = s.rfind("]")
    if lb < 0 or rb <= lb:
        return None
    try:
        return json.loads(s[lb : rb + 1])
    except (TypeError, ValueError):
        return None


def _deepseek_graph_row_intros(topic: str, graph_rows: List[dict]) -> Dict[str, str]:
    """为扩展推荐表生成 book_key -> 简介（Markdown 允许）。无 API Key 或关闭开关时返回 {}。"""
    if not graph_rows:
        return {}
    if not (os.environ.get("DEEPSEEK_API_KEY") or "").strip():
        return {}
    flag = (os.environ.get("READING_GRAPH_INTRO_DEEPSEEK") or "1").strip().lower()
    if flag in ("0", "false", "off", "no"):
        return {}
    compact: List[Dict[str, Any]] = []
    for gr in graph_rows[:12]:
        bk = str(gr.get("book_key") or "").strip()
        title = (gr.get("title") or "").strip()
        if not title:
            continue
        sm = (str(gr.get("summary") or "").strip())[:240]
        authors = gr.get("authors") if isinstance(gr.get("authors"), list) else []
        compact.append(
            {
                "book_key": bk,
                "title": title,
                "authors": [str(a) for a in authors if str(a).strip()][:4],
                "rating": gr.get("rating"),
                "summary_snippet": sm,
            }
        )
    if not compact:
        return {}
    user_blob = (
        f"检索主题：{topic}\n\n"
        "候选书 JSON：\n"
        f"{json.dumps(compact, ensure_ascii=False)}\n\n"
        "请输出 JSON 数组，字段 book_key、intro。"
    )
    raw, err = deepseek_chat(
        user_blob,
        system=_GRAPH_INTRO_DEEPSEEK_SYSTEM,
        timeout=50.0,
        temperature=0.35,
    )
    if not raw or err:
        if err and err != "missing_api_key":
            logging.getLogger(__name__).info("graph intro DeepSeek: %s", err)
        return {}
    arr = _extract_first_json_array(raw)
    if not isinstance(arr, list):
        return {}
    out: Dict[str, str] = {}
    for el in arr:
        if not isinstance(el, dict):
            continue
        bk = str(el.get("book_key") or "").strip()
        intro = str(el.get("intro") or "").strip()
        if bk and intro:
            out[bk] = intro
    return out


def _deepseek_off_catalog_rows(topic: str, catalog_rows: List[dict], web_ctx: str) -> List[Dict[str, str]]:
    """模型补充：主题相关但不在演示馆藏表中的延伸书目（仅 JSON 解析结果，无 API 时返回 []）。"""
    if not (os.environ.get("DEEPSEEK_API_KEY") or "").strip():
        return []
    flag = (os.environ.get("READING_OFFCATALOG_DEEPSEEK") or "1").strip().lower()
    if flag in ("0", "false", "off", "no"):
        return []
    lib_titles = sorted(
        {str(r.get("lib_book") or "").strip() for r in (catalog_rows or []) if str(r.get("lib_book") or "").strip()}
    )
    user_blob = (
        f"阅读主题：{topic}\n\n"
        "【本馆演示库已有书目（勿重复推荐）】\n"
        f"{json.dumps(lib_titles[:50], ensure_ascii=False)}\n"
    )
    wc = (web_ctx or "").strip()
    if wc:
        user_blob += f"\n【网络参考（可借鉴题材与读法，勿当成本馆目录）】\n{wc[:2200]}\n"
    user_blob += "\n请严格只输出 JSON 数组，元素字段 title、note。"
    raw, err = deepseek_chat(
        user_blob,
        system=_READING_OFFCATALOG_SYSTEM,
        timeout=48.0,
        temperature=0.42,
    )
    if not raw or err:
        if err and err != "missing_api_key":
            logging.getLogger(__name__).info("reading off-catalog DeepSeek: %s", err)
        return []
    arr = _extract_first_json_array(raw)
    if not isinstance(arr, list):
        return []
    out: List[Dict[str, str]] = []
    for el in arr:
        if not isinstance(el, dict):
            continue
        title = str(el.get("title") or "").strip()
        note = str(el.get("note") or "").strip()
        if not title or not note:
            continue
        if _match_catalog_title(catalog_rows, title):
            continue
        out.append({"book_title": title, "note": (note[:220] + "…") if len(note) > 220 else note})
        if len(out) >= 8:
            break
    return out


def _reading_recommend_custom_message(
    topic: str,
    catalog_rows: List[dict],
    graph_extension_rows: List[dict],
    graph_ai_summaries: Optional[Dict[str, str]] = None,
    off_catalog_rows: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """结构化载荷：馆藏只在「本馆」表；图谱补充表不含已命中馆藏；馆外延伸来自模型 JSON。"""
    graph_ai_summaries = graph_ai_summaries or {}
    off_catalog_rows = off_catalog_rows or []
    on_shelf = [r for r in catalog_rows if int(r.get("is_borrow") or 0) == 0]
    borrowed = [r for r in catalog_rows if int(r.get("is_borrow") or 0) == 1]

    def cat_row(r: dict) -> Dict[str, Any]:
        sm = str(r.get("summary") or "").strip()
        return {
            "book_title": str(r.get("lib_book") or "").strip(),
            "call_number": str(r.get("book_key") or "").strip(),
            "book_pos": (str(r.get("book_pos") or "").strip() or "未定"),
            "book_summary": (sm[:200] + "…") if len(sm) > 200 else sm,
            "status": _circulation_label(r),
        }

    graph_out: List[Dict[str, Any]] = []
    for gr in graph_extension_rows:
        title = (gr.get("title") or "").strip()
        if not title:
            continue
        m = _match_catalog_title(catalog_rows, title)
        sm = (gr.get("summary") or "").strip()
        sm_short = (sm[:180] + "…") if len(sm) > 180 else sm
        rating = gr.get("rating")
        authors = gr.get("authors") or []
        author_bios = gr.get("author_bios") or []
        categories = gr.get("categories") or []
        disciplines = gr.get("disciplines") or []
        related_authors = gr.get("related_authors") or []
        topics = gr.get("topics") or []
        if not isinstance(authors, list):
            authors = []
        if not isinstance(author_bios, list):
            author_bios = []
        if not isinstance(categories, list):
            categories = []
        if not isinstance(disciplines, list):
            disciplines = []
        if not isinstance(related_authors, list):
            related_authors = []
        if not isinstance(topics, list):
            topics = []
        hint_parts: List[str] = []
        if authors:
            hint_parts.append("作者：" + "、".join(str(a) for a in authors if str(a).strip()))
        for i, name in enumerate(authors):
            if i < len(author_bios) and (author_bios[i] or "").strip():
                bio_s = str(author_bios[i]).strip()
                hint_parts.append(
                    f"{name}简介：" + (bio_s[:120] + "…" if len(bio_s) > 120 else bio_s)
                )
                break
        if disciplines:
            hint_parts.append("学科：" + "、".join(str(d) for d in disciplines if str(d).strip()))
        elif categories:
            hint_parts.append("类目：" + "、".join(str(c) for c in categories if str(c).strip()))
        if related_authors:
            hint_parts.append(
                "关联作者：" + "、".join(str(a) for a in related_authors if str(a).strip())[:80]
            )
        if topics:
            hint_parts.append("主题：" + "、".join(str(t) for t in topics if str(t).strip()))
        if rating is not None:
            hint_parts.append(f"评分 {rating}")
        if sm_short:
            hint_parts.append(sm_short)
        c_sum = (str(m.get("summary") or "").strip()) if m else ""
        gk = str(gr.get("book_key") or "").strip()
        call_no = (str(m.get("book_key") or "").strip() if m else "") or gk or "—"
        fallback_sm = (c_sum[:200] + "…") if len(c_sum) > 200 else (c_sum or sm_short or "")
        ai_sm = (graph_ai_summaries.get(call_no) or graph_ai_summaries.get(gk) or "").strip()
        graph_out.append(
            {
                "book_title": title,
                "call_number": call_no,
                "book_summary": ai_sm or fallback_sm or "—",
                "hint": "；".join(hint_parts) if hint_parts else "—",
            }
        )

    return {
        "payload_type": "reading_recommend",
        "topic": topic,
        "intro": (
            f"主题「{topic}」｜下方首表为演示库**本馆馆藏**（在架与已借出）；"
            "次表为图谱补充（未出现在主题检索表中的本馆关联书）；末表为**非演示馆藏**的延伸阅读。"
        ),
        "on_shelf_rows": [cat_row(r) for r in on_shelf[:40]],
        "borrowed_rows": [cat_row(r) for r in borrowed[:40]],
        "graph_rows": graph_out[:12],
        "off_catalog_rows": off_catalog_rows[:12],
        "footnote": (
            "在架与索书号以「本馆馆藏」表为准；图谱补充仍为本馆节点时以 Neo4j 为准；"
            "「非本馆演示藏书」由模型生成，**未承诺已采购或已编目**，仅供阅读拓展。"
        ),
    }


def _deepseek_multi_intent_system() -> str:
    """意图覆盖 + 检索场景下的 system 提示（借还办理边界）。"""
    anchor = borrow_policy_anchor()
    extra = (
        "用户一句话可能涉及多个主题；请分点简要回应。"
        "涉及实际借书、还书「办理」时，只引导用户在本对话中说「借书」或「还书」进入系统流程，不要声称已代为办理或改变借阅规则。"
    )
    parts = [_DATA_INQUIRY_SYSTEM]
    if anchor:
        parts.append(anchor)
    parts.append(extra)
    return "\n\n".join(parts)


def _normalize_title_from_text(text: Any) -> str:
    raw = (str(text or "")).strip()
    if not raw:
        return ""
    m = re.search(r"《([^》]+)》", raw)
    if m:
        return " ".join(m.group(1).split())
    raw = re.sub(r"^\s*\d+\s*[\.、]\s*", " ", raw)
    raw = re.sub(r"[（(][A-Z0-9\.\-_/]+[）)]", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[—\-]\s*[^（(]*?(?:架|库)", " ", raw)
    for p in ["我想借", "我要借", "帮我借", "借一本", "借", "我想还", "我要还", "归还", "还一本", "还"]:
        raw = raw.replace(p, " ")
    for p in ["吗", "呢", "呀", "吧", "啊", "，", "。", "？", "！", ",", ".", "?", "!"]:
        raw = raw.replace(p, " ")
    return " ".join(raw.split())


def _is_generic_borrow_command(text: Any) -> bool:
    raw = (str(text or "")).strip()
    if not raw:
        return False
    compact = re.sub(r"\s+", "", raw)
    patterns = (
        r"^(我)?(想|要)?(来)?借书$",
        r"^借书$",
        r"^借一下$",
        r"^帮我借书$",
        r"^我要办理借阅$",
        r"^办理借阅$",
    )
    return any(re.fullmatch(p, compact) for p in patterns)


def _is_demo_book_reference(text: Any) -> bool:
    raw = (str(text or "")).strip()
    if not raw:
        return False
    keys = (
        "这本",
        "那本",
        "就这本",
        "就那本",
        "借这本",
        "借那本",
        "那就借这本",
        "那就借这一本",
        "借它",
        "就它",
    )
    return any(k in raw for k in keys)


def _pick_recommended_title_from_text(text: Any, candidates_raw: Any) -> Optional[str]:
    raw = (str(text or "")).strip()
    if not raw:
        return None
    try:
        candidates = json.loads(str(candidates_raw or "[]"))
    except Exception:
        candidates = []
    if not isinstance(candidates, list):
        return None
    titles = [str(x).strip() for x in candidates if str(x).strip()]
    if not titles:
        return None
    m = re.search(r"第\s*(\d{1,2})\s*(?:本|条|个)", raw)
    if m:
        idx = int(m.group(1))
        if 1 <= idx <= len(titles):
            return titles[idx - 1]
    return None


def _normalize_call_input(raw: Any) -> str:
    text = (str(raw or "")).strip()
    text = text.replace("索书号", " ").replace("条码", " ").replace("：", " ").replace(":", " ")
    return " ".join(text.split()).upper()


def _pick_call_number(raw: str, rows: List[Dict[str, Any]]) -> Optional[str]:
    if not raw:
        return None
    keys = [(r.get("book_key") or "").strip().upper() for r in rows if (r.get("book_key") or "").strip()]
    if not keys:
        return None
    if raw in keys:
        return raw
    for k in keys:
        if raw == k or raw in k or k in raw:
            return k
    m = re.fullmatch(r"(?:第)?\s*(\d{1,2})\s*(?:本|条|个)?", raw)
    if m:
        idx = int(m.group(1))
        if 1 <= idx <= len(keys):
            return keys[idx - 1]
    return None


def _dedupe_rows_by_call_number(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按索书号去重并稳定排序，避免同一索书号重复展示。"""
    by_call: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        call_no = (row.get("book_key") or "").strip().upper()
        if not call_no:
            continue
        if call_no not in by_call:
            by_call[call_no] = row
    return [by_call[k] for k in sorted(by_call.keys())]


class ValidateBorrowBookForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_borrow_book_form"

    async def validate_book_title(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        latest_text = tracker.latest_message.get("text") or ""
        if _is_generic_borrow_command(latest_text):
            return {"book_title": None}
        picked_from_rec = _pick_recommended_title_from_text(
            latest_text, tracker.get_slot("last_recommended_candidates")
        )
        if picked_from_rec:
            return {"book_title": picked_from_rec}
        if _is_demo_book_reference(latest_text):
            remembered = (tracker.get_slot("last_recommended_title") or "").strip()
            if remembered:
                return {"book_title": remembered}
        title = _normalize_title_from_text(slot_value) if slot_value else ""
        if title:
            return {"book_title": title}
        latest = _normalize_title_from_text(latest_text)
        if not latest:
            return {"book_title": None}
        rows = list_on_shelf_by_title(latest, limit=1)
        if rows:
            return {"book_title": rows[0]["lib_book"]}
        return {"book_title": latest}


class ActionAskBorrowBookFormBookTitle(Action):
    """借书时返回可交互书目清单（前端本地查询/翻页）。"""

    def name(self) -> Text:
        return "action_ask_borrow_book_form_book_title"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        borrower_id = (tracker.sender_id or "").strip()
        active_count = get_active_borrow_count(borrower_id)
        active_rows = [
            r for r in list_borrow_records(borrower_id, limit=20) if not (r.get("returned_at") or "").strip()
        ]
        rows = _dedupe_rows_by_call_number(list_catalog_books(limit=500))
        payload_rows = []
        for r in rows:
            borrowed = int(r.get("is_borrow") or 0) == 1
            payload_rows.append(
                {
                    "book_title": r.get("lib_book") or "",
                    "call_number": r.get("book_key") or "",
                    "book_pos": r.get("book_pos") or "位置未定",
                    "book_summary": (str(r.get("summary") or "").strip()[:300]),
                    "status": "已借出" if borrowed else "在架可借",
                    "is_available": not borrowed,
                }
            )
        intro = "请问要办理的书名是？可在下方书目表中搜索并翻页选择。"
        empty_hint = ""
        if not payload_rows:
            empty_hint = (
                " 若书目为空：请确认 Neo4j 已启动、根目录 `.env` 已配置 NEO4J_*，"
                "并执行 `python scripts/seed_library_graph.py` 后重启 Action。"
            )
        dispatcher.utter_message(
            text=intro + empty_hint,
            json_message={
                "payload_type": "borrow_catalog",
                "rows": payload_rows,
                "total": len(payload_rows),
                "borrow_policy": {
                    "borrower_id": borrower_id,
                    "active_count": active_count,
                    "max_active": 3,
                    "can_borrow": active_count < 3,
                    "message": (
                        f"当前账号（{borrower_id}）已借 {active_count}/3 本；"
                        + ("可继续借阅。" if active_count < 3 else "已达上限，请先归还后再借。")
                    ),
                    "active_books": [
                        {
                            "book_title": str(x.get("lib_book") or "").strip(),
                            "call_number": str(x.get("book_key") or "").strip(),
                        }
                        for x in active_rows
                    ],
                },
            },
        )
        return []


class ActionAskReturnBookFormBookTitle(Action):
    def name(self) -> Text:
        return "action_ask_return_book_form_book_title"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        borrower_id = (tracker.sender_id or "").strip()
        rows = list_active_borrow_records(borrower_id, limit=120)
        catalog_rows = [
            {
                "book_title": str(r.get("lib_book") or "").strip(),
                "call_number": str(r.get("book_key") or "").strip(),
                "book_pos": str(r.get("book_pos") or "").strip(),
                "book_summary": str(r.get("summary") or "").strip(),
                "borrow_at": str(r.get("borrow_at") or "").strip(),
                "due_at": str(r.get("due_at") or "").strip(),
                "status": "待归还",
                "can_return": True,
            }
            for r in rows
            if (str(r.get("book_key") or "").strip() and str(r.get("lib_book") or "").strip())
        ]
        msg = (
            f"当前账号（{borrower_id}）待还 {len(catalog_rows)} 本；"
            + ("可在下方选择并批量归还。" if catalog_rows else "暂无待还图书。")
        )
        dispatcher.utter_message(
            text="请问要办理归还的书名是？可在下方待还列表中搜索并翻页选择。",
            json_message={
                "payload_type": "return_catalog",
                "rows": catalog_rows,
                "total": len(catalog_rows),
                "return_policy": {
                    "borrower_id": borrower_id,
                    "active_count": len(catalog_rows),
                    "can_return": len(catalog_rows) > 0,
                    "message": msg,
                },
            },
        )
        return []


class ActionBorrowBookFormSubmit(Action):
    def name(self) -> Text:
        return "action_borrow_book_form_submit"

    def run(self, dispatcher, tracker, domain):
        title = (tracker.get_slot("book_title") or "").strip()
        metadata = tracker.latest_message.get("metadata") or {}
        # 兜底：若会话状态串线误入借书提交，但前端实际提交的是 return_profile，则按还书直办处理。
        return_profile = metadata.get("return_profile") if isinstance(metadata, dict) else {}
        if isinstance(return_profile, dict):
            prof_call = _normalize_call_input(return_profile.get("callNumber"))
            prof_title = (str(return_profile.get("bookTitle") or "")).strip() or title
            if prof_call:
                borrower_id = (tracker.sender_id or "").strip()
                ok, _, detail = return_book(prof_title, prof_call, borrower_id=borrower_id)
                dispatcher.utter_message(text=detail)
                return [
                    AllSlotsReset(),
                    SlotSet("api_return_succeed", ok),
                    SlotSet("last_return_detail", detail),
                    ActiveLoop(None),
                    FollowupAction("action_listen"),
                ]
        profile = metadata.get("borrow_profile") if isinstance(metadata, dict) else {}
        # 前端批量提交会携带 borrow_profile：此处直办借阅，避免再依赖“确认”意图识别。
        if isinstance(profile, dict):
            prof_call = _normalize_call_input(profile.get("callNumber"))
            prof_title = (str(profile.get("bookTitle") or "")).strip() or title
            if prof_call:
                borrower_id = (tracker.sender_id or "").strip()
                contact = str(profile.get("studentOrPhone") or "").strip()
                display_name = str(profile.get("name") or borrower_id).strip() or borrower_id
                if contact:
                    display_name = f"{display_name}（{contact}）"
                ok, book_info, detail = borrow_book(prof_title, prof_call, borrower_id=borrower_id)
                if ok:
                    written = record_borrow_transaction(
                        book_snapshot=book_info,
                        borrower_id=borrower_id,
                        borrower_name=display_name,
                        borrow_at=str(profile.get("borrowAt") or ""),
                        due_at=str(profile.get("dueAt") or ""),
                    )
                    if written:
                        detail = f"{detail}\n已登记借阅人信息。"
                dispatcher.utter_message(text=detail)
                return [
                    AllSlotsReset(),
                    SlotSet("api_borrow_succeed", ok),
                    SlotSet("last_borrow_detail", detail),
                    ActiveLoop(None),
                    FollowupAction("action_listen"),
                ]
        rows = _dedupe_rows_by_call_number(list_on_shelf_by_title(title))
        if not rows:
            dispatcher.utter_message(
                text=(
                    "演示库中暂无与您输入匹配的在架可借副本（可能未命中书名，或该题名下可借副本均已借出）。"
                    "请换一个关键词或书名再试。"
                )
            )
            return [
                SlotSet("borrow_phase", "empty"),
                SlotSet("defer_nlu_fallback", False),
                SlotSet("call_number", None),
                SlotSet("book_title", None),
                ActiveLoop(None),
                FollowupAction("action_listen"),
            ]

        if len(rows) == 1:
            r = rows[0]
            call_no = (r.get("book_key") or "").strip()
            dispatcher.utter_message(
                text=f"确认借阅《{r['lib_book']}》（索书号 {call_no}）吗？"
            )
            return [
                SlotSet("borrow_phase", "single_confirm"),
                SlotSet("defer_nlu_fallback", False),
                SlotSet("call_number", call_no),
                FollowupAction("action_listen"),
            ]

        lines = [
            f"{i}. 《{r['lib_book']}》 索书号 {r['book_key']}，架位 {r.get('book_pos') or '未定'}"
            for i, r in enumerate(rows, start=1)
        ]
        dispatcher.utter_message(
            text=(
                f"在架可借共 {len(rows)} 本（已省略已借出副本）：\n"
                + "\n".join(lines)
                + "\n请直接回复要借的那一条索书号。"
            )
        )
        return [
            SlotSet("borrow_phase", "multi_pick"),
            SlotSet("defer_nlu_fallback", True),
            SlotSet("call_number", None),
            ActiveLoop("borrow_call_form"),
            FollowupAction("action_listen"),
        ]


class ValidateBorrowCallForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_borrow_call_form"

    async def validate_call_number(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        raw = (str(slot_value).strip() if slot_value not in (None, "") else "") or (
            tracker.latest_message.get("text") or ""
        ).strip()
        if _is_generic_borrow_command(raw):
            return {"call_number": None}
        raw = _normalize_call_input(raw)
        title = (tracker.get_slot("book_title") or "").strip()
        if not raw:
            return {"call_number": None}
        rows = _dedupe_rows_by_call_number(list_on_shelf_by_title(title))
        picked = _pick_call_number(raw, rows)
        if picked:
            return {"call_number": picked}
        return {"call_number": None}


class ActionBorrowCallFormSubmit(Action):
    def name(self) -> Text:
        return "action_borrow_call_form_submit"

    def run(self, dispatcher, tracker, domain):
        title = (tracker.get_slot("book_title") or "").strip()
        call_no = _normalize_call_input(tracker.get_slot("call_number"))
        if not call_no:
            dispatcher.utter_message(
                text="未识别到有效输入。请从上方「在架可借」列表中回复一条索书号或序号。"
            )
            return [
                SlotSet("defer_nlu_fallback", True),
                SlotSet("call_number", None),
                ActiveLoop("borrow_call_form"),
            ]
        rows = _dedupe_rows_by_call_number(list_on_shelf_by_title(title))
        resolved = _pick_call_number(call_no, rows)
        if not resolved:
            dispatcher.utter_message(
                text="该输入不在当前可借列表中，或书目已变更。请重新从列表中选择索书号或序号。"
            )
            return [
                SlotSet("defer_nlu_fallback", True),
                SlotSet("call_number", None),
                ActiveLoop("borrow_call_form"),
            ]
        call_no = resolved
        row = next((x for x in rows if (x.get("book_key") or "").strip() == call_no), None)
        if not row:
            dispatcher.utter_message(text="书目状态已变更，请重新输入书名查询在架副本。")
            return [
                SlotSet("borrow_phase", "empty"),
                SlotSet("defer_nlu_fallback", False),
                SlotSet("call_number", None),
                SlotSet("book_title", None),
                ActiveLoop(None),
                FollowupAction("action_listen"),
            ]
        dispatcher.utter_message(
            text=f"确认借阅《{row['lib_book']}》（索书号 {call_no}）吗？"
        )
        return [
            SlotSet("call_number", call_no),
            SlotSet("defer_nlu_fallback", False),
        ]


class ActionBorrowBook(Action):
    def name(self) -> Text:
        return "action_borrow_book"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        title = (tracker.get_slot("book_title") or "").strip()
        call_no = (tracker.get_slot("call_number") or "").strip()
        metadata = tracker.latest_message.get("metadata") or {}
        profile = metadata.get("borrow_profile") if isinstance(metadata, dict) else {}
        borrower_id = (tracker.sender_id or "").strip()
        ok, book_info, detail = borrow_book(title, call_no, borrower_id=borrower_id)
        if ok and isinstance(profile, dict):
            contact = str(profile.get("studentOrPhone") or "").strip()
            display_name = str(profile.get("name") or borrower_id).strip() or borrower_id
            if contact:
                display_name = f"{display_name}（{contact}）"
            written = record_borrow_transaction(
                book_snapshot=book_info,
                borrower_id=borrower_id,
                borrower_name=display_name,
                borrow_at=str(profile.get("borrowAt") or ""),
                due_at=str(profile.get("dueAt") or ""),
            )
            if written:
                detail = f"{detail}\n已登记借阅人信息。"
        return [
            AllSlotsReset(),
            SlotSet("api_borrow_succeed", ok),
            SlotSet("last_borrow_detail", detail),
            ActiveLoop(None),
        ]


class ActionBorrowConfirmCancel(Action):
    """用户在单本/多本借书确认阶段否定：统一话术并清理借书相关槽位，避免后续意图被旧状态干扰。"""

    def name(self) -> Text:
        return "action_borrow_confirm_cancel"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(response="utter_ask_borrow_confirm_then_no")
        return [
            SlotSet("borrow_phase", "idle"),
            SlotSet("book_title", None),
            SlotSet("call_number", None),
            SlotSet("defer_nlu_fallback", False),
            ActiveLoop(None),
        ]


class ActionReturnConfirmCancel(Action):
    """用户在单本/多本还书确认阶段否定：统一话术并清理还书相关槽位。"""

    def name(self) -> Text:
        return "action_return_confirm_cancel"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(response="utter_ask_return_confirm_then_no")
        return [
            SlotSet("return_phase", "idle"),
            SlotSet("book_title", None),
            SlotSet("call_number", None),
            SlotSet("defer_nlu_fallback", False),
            ActiveLoop(None),
        ]


class ValidateReturnBookForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_return_book_form"

    async def validate_book_title(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        title = _normalize_title_from_text(slot_value) if slot_value else ""
        if title:
            return {"book_title": title}
        latest = _normalize_title_from_text(tracker.latest_message.get("text"))
        if not latest:
            return {"book_title": None}
        rows = list_borrowed_by_title(latest, limit=1)
        if rows:
            return {"book_title": rows[0]["lib_book"]}
        return {"book_title": latest}


class ActionReturnBookFormSubmit(Action):
    def name(self) -> Text:
        return "action_return_book_form_submit"

    def run(self, dispatcher, tracker, domain):
        title = (tracker.get_slot("book_title") or "").strip()
        metadata = tracker.latest_message.get("metadata") or {}
        profile = metadata.get("return_profile") if isinstance(metadata, dict) else {}
        if isinstance(profile, dict):
            prof_call = _normalize_call_input(profile.get("callNumber"))
            prof_title = (str(profile.get("bookTitle") or "")).strip() or title
            if prof_call:
                borrower_id = (tracker.sender_id or "").strip()
                ok, _, detail = return_book(prof_title, prof_call, borrower_id=borrower_id)
                dispatcher.utter_message(text=detail)
                return [
                    AllSlotsReset(),
                    SlotSet("api_return_succeed", ok),
                    SlotSet("last_return_detail", detail),
                    ActiveLoop(None),
                    FollowupAction("action_listen"),
                ]
        rows = list_borrowed_by_title(title)
        if not rows:
            dispatcher.utter_message(
                text=(
                    "演示库中暂无与您输入匹配的「已借出」副本（可能未命中书名，或该题名下无待还记录）。"
                    "请核对书名；若仅想还其中一本，可尝试更完整的书名关键词。"
                )
            )
            return [
                SlotSet("return_phase", "empty"),
                SlotSet("defer_nlu_fallback", False),
                SlotSet("call_number", None),
                SlotSet("book_title", None),
                ActiveLoop(None),
                FollowupAction("action_listen"),
            ]

        if len(rows) == 1:
            r = rows[0]
            call_no = (r.get("book_key") or "").strip()
            dispatcher.utter_message(
                text=(
                    f"待还记录（1 条）：《{r['lib_book']}》 索书号 {r['book_key']}，"
                    f"架位 {r.get('book_pos') or '未定'}。"
                )
            )
            dispatcher.utter_message(text=lookup_circulation(title, call_no))
            dispatcher.utter_message(
                text=f"确认归还《{title}》（索书号 {call_no}）吗？"
            )
            return [
                SlotSet("return_phase", "single_confirm"),
                SlotSet("defer_nlu_fallback", False),
                SlotSet("call_number", call_no),
            ]

        lines = [
            f"{i}. 《{r['lib_book']}》 索书号 {r['book_key']}，架位 {r.get('book_pos') or '未定'}"
            for i, r in enumerate(rows, start=1)
        ]
        dispatcher.utter_message(
            text=(
                f"待还共 {len(rows)} 条（仅列出已借出副本）：\n"
                + "\n".join(lines)
                + "\n请直接回复要还的那一条索书号。"
            )
        )
        return [
            SlotSet("return_phase", "multi_pick"),
            SlotSet("defer_nlu_fallback", True),
            SlotSet("call_number", None),
            ActiveLoop("return_call_form"),
        ]


class ValidateReturnCallForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_return_call_form"

    async def validate_call_number(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        raw = (str(slot_value).strip() if slot_value not in (None, "") else "") or (
            tracker.latest_message.get("text") or ""
        ).strip()
        if "还书" in raw:
            return {"call_number": None}
        raw = _normalize_call_input(raw)
        title = (tracker.get_slot("book_title") or "").strip()
        if not raw:
            return {"call_number": None}
        rows = list_borrowed_by_title(title)
        picked = _pick_call_number(raw, rows)
        if picked:
            return {"call_number": picked}
        return {"call_number": None}


class ActionReturnCallFormSubmit(Action):
    def name(self) -> Text:
        return "action_return_call_form_submit"

    def run(self, dispatcher, tracker, domain):
        title = (tracker.get_slot("book_title") or "").strip()
        call_no = _normalize_call_input(tracker.get_slot("call_number"))
        if not call_no:
            dispatcher.utter_message(
                text="未识别到有效输入。请从上方「待还」列表中回复一条索书号或序号。"
            )
            return [
                SlotSet("defer_nlu_fallback", True),
                SlotSet("call_number", None),
                ActiveLoop("return_call_form"),
            ]
        rows = list_borrowed_by_title(title)
        resolved = _pick_call_number(call_no, rows)
        if not resolved:
            dispatcher.utter_message(
                text="该输入不在当前待还列表中。请重新从列表中选择索书号或序号。"
            )
            return [
                SlotSet("defer_nlu_fallback", True),
                SlotSet("call_number", None),
                ActiveLoop("return_call_form"),
            ]
        call_no = resolved
        dispatcher.utter_message(text=lookup_circulation(title, call_no))
        dispatcher.utter_message(
            text=f"确认归还《{title}》（索书号 {call_no}）吗？"
        )
        return [
            SlotSet("call_number", call_no),
            SlotSet("defer_nlu_fallback", False),
        ]


class ActionReturnBook(Action):
    def name(self) -> Text:
        return "action_return_book"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        title = (tracker.get_slot("book_title") or "").strip()
        call_no = (tracker.get_slot("call_number") or "").strip()
        borrower_id = (tracker.sender_id or "").strip()
        ok, _, detail = return_book(title, call_no, borrower_id=borrower_id)
        return [
            AllSlotsReset(),
            SlotSet("api_return_succeed", ok),
            SlotSet("last_return_detail", detail),
            ActiveLoop(None),
            FollowupAction("action_listen"),
        ]


class ValidateSpaceBookingForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_space_booking_form"

    @staticmethod
    def _latest_text(tracker: Tracker) -> str:
        return (tracker.latest_message.get("text") or "").strip()

    async def validate_room_type(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        raw = (str(slot_value).strip() if slot_value not in (None, "") else "") or self._latest_text(
            tracker
        )
        if not raw:
            dispatcher.utter_message(
                text="请直接回复空间类型，例如：研讨间、自习座位、静音阅览区（「研讨室」与「研讨间」均可）。"
            )
            return {"room_type": None}
        if "研讨" in raw or "研讨室" in raw:
            return {"room_type": "研讨间"}
        if "自习" in raw or ("座位" in raw and "静音" not in raw):
            return {"room_type": "自习座位"}
        if "静音" in raw:
            return {"room_type": "静音阅览区"}
        return {"room_type": raw}

    async def validate_time_slot(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        raw = (str(slot_value).strip() if slot_value not in (None, "") else "") or self._latest_text(
            tracker
        )
        if not raw:
            dispatcher.utter_message(text="请说一下方便的时间段，例如「明天下午」「周五上午」。")
            return {"time_slot": None}
        return {"time_slot": raw}


class ActionSpaceBookingFormSubmit(Action):
    def name(self) -> Text:
        return "action_space_booking_form_submit"

    def run(self, dispatcher, tracker, domain):
        dispatcher.utter_message(response="utter_ask_space_confirm", **tracker.slots)
        return []


class ActionSpaceBooking(Action):
    def name(self) -> Text:
        return "action_space_booking"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        room = (tracker.get_slot("room_type") or "").strip()
        when = (tracker.get_slot("time_slot") or "").strip()
        ok = ("研讨" in room) and ("下午" in when)
        return [
            AllSlotsReset(),
            SlotSet("api_space_book_succeed", ok),
            ActiveLoop(None),
        ]


class ActionReadingRecommend(Action):
    def name(self) -> Text:
        return "action_reading_recommend"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        topic = _resolve_reading_topic(tracker)
        if not topic:
            dispatcher.utter_message(
                text=(
                    "推荐阅读：请用简短词语告诉我**感兴趣的主题或作者**。"
                    "举例仅为常见说法，**没有系统默认主题**——例如可说「人工智能」「文学」「历史」，或作者名如「刘慈欣」；"
                    "也可以说「推荐几本心理学入门」。"
                )
            )
            return []

        try:
            cat_limit = int(os.environ.get("READING_RECOMMEND_CATALOG_LIMIT") or "50")
        except ValueError:
            cat_limit = 50
        cat_limit = max(10, min(cat_limit, 120))

        catalog_rows = catalog_search_by_topic(topic, cat_limit)
        graph_rows = neo4j_recommend_by_topic(topic, limit=8)

        if not catalog_rows and not graph_rows:
            dispatcher.utter_message(
                text=(
                    f"演示库与图谱中均未找到与「{topic}」匹配的书目，可换一个关键词；"
                    "也可先说「书籍总览」浏览演示馆藏。"
                )
            )
            return [
                SlotSet("last_recommended_title", None),
                SlotSet("last_recommended_call_number", None),
                SlotSet("last_recommended_candidates", None),
            ]

        web_ctx = build_reading_web_context(topic)

        ds_flag = (os.environ.get("READING_RECOMMEND_DEEPSEEK") or "1").strip().lower()
        if ds_flag not in ("0", "false", "off", "no"):
            facts = _reading_facts_dict(catalog_rows, graph_rows)
            user_blob = (
                f"用户输入原句：{(tracker.latest_message.get('text') or '').strip()}\n"
                f"解析主题/检索词：{topic}\n\n"
                f"【馆内检索事实 JSON】\n{json.dumps(facts, ensure_ascii=False)}"
            )
            if web_ctx:
                user_blob += f"\n\n【网络参考】\n{web_ctx}"
            ds_text, ds_err = deepseek_chat(
                user_blob,
                system=_READING_DEEPSEEK_SYSTEM,
                timeout=55.0,
                temperature=0.45,
            )
            if ds_text:
                dispatcher.utter_message(text=ds_text.strip())
            elif ds_err and ds_err != "missing_api_key":
                logging.getLogger(__name__).info("reading_recommend DeepSeek 跳过: %s", ds_err)

        cat_keys = _catalog_book_key_set(catalog_rows)
        graph_ext = [gr for gr in graph_rows if not _graph_row_in_catalog(gr, catalog_rows, cat_keys)]
        graph_ai_summaries = _deepseek_graph_row_intros(topic, graph_ext)

        off_catalog_rows: List[Dict[str, str]] = []
        off_flag = (os.environ.get("READING_OFFCATALOG_DEEPSEEK") or "1").strip().lower()
        if off_flag not in ("0", "false", "off", "no"):
            off_catalog_rows = _deepseek_off_catalog_rows(topic, catalog_rows, web_ctx)

        dispatcher.utter_message(
            json_message=_reading_recommend_custom_message(
                topic,
                catalog_rows,
                graph_ext,
                graph_ai_summaries=graph_ai_summaries,
                off_catalog_rows=off_catalog_rows,
            )
        )

        on_shelf = [r for r in catalog_rows if int(r.get("is_borrow") or 0) == 0]
        borrowed = [r for r in catalog_rows if int(r.get("is_borrow") or 0) == 1]
        ordered_titles: List[str] = []
        for r in on_shelf:
            t = str(r.get("lib_book") or "").strip()
            if t and t not in ordered_titles:
                ordered_titles.append(t)
        for r in borrowed:
            t = str(r.get("lib_book") or "").strip()
            if t and t not in ordered_titles:
                ordered_titles.append(t)
        for gr in graph_ext:
            t = str(gr.get("title") or "").strip()
            if t and t not in ordered_titles:
                ordered_titles.append(t)
        for oc in off_catalog_rows:
            t = str(oc.get("book_title") or "").strip()
            if t and t not in ordered_titles:
                ordered_titles.append(t)

        if on_shelf:
            pick = on_shelf[0]
            return [
                SlotSet("last_recommended_title", pick["lib_book"]),
                SlotSet("last_recommended_call_number", pick["book_key"]),
                SlotSet(
                    "last_recommended_candidates",
                    json.dumps(ordered_titles[:20], ensure_ascii=False),
                ),
            ]
        if borrowed:
            pick = borrowed[0]
            return [
                SlotSet("last_recommended_title", pick["lib_book"]),
                SlotSet("last_recommended_call_number", pick["book_key"]),
                SlotSet(
                    "last_recommended_candidates",
                    json.dumps(ordered_titles[:20], ensure_ascii=False),
                ),
            ]
        if graph_ext:
            top = graph_ext[0]
            tk = str(top.get("book_key") or "").strip()
            return [
                SlotSet("last_recommended_title", (top.get("title") or "").strip() or None),
                SlotSet("last_recommended_call_number", tk or None),
                SlotSet(
                    "last_recommended_candidates",
                    json.dumps(ordered_titles[:20], ensure_ascii=False),
                ),
            ]
        if off_catalog_rows:
            pick = off_catalog_rows[0]
            return [
                SlotSet("last_recommended_title", (pick.get("book_title") or "").strip() or None),
                SlotSet("last_recommended_call_number", None),
                SlotSet(
                    "last_recommended_candidates",
                    json.dumps(ordered_titles[:20], ensure_ascii=False),
                ),
            ]
        return [
            SlotSet("last_recommended_title", None),
            SlotSet("last_recommended_call_number", None),
            SlotSet("last_recommended_candidates", None),
        ]


class ActionBookOverview(Action):
    def name(self) -> Text:
        return "action_book_overview"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        metadata = tracker.latest_message.get("metadata") or {}
        oc_raw = metadata.get("overview_catalog") if isinstance(metadata, dict) else None
        oc = oc_raw if isinstance(oc_raw, dict) else {}
        intent_name = (tracker.latest_message.get("intent") or {}).get("name") or ""

        try:
            ps = int(oc.get("page_size") or 10)
        except (TypeError, ValueError):
            ps = 10
        ps = max(5, min(30, ps))

        if intent_name == "book_overview":
            page = 1
        else:
            try:
                page = int(oc.get("page") or 1)
            except (TypeError, ValueError):
                page = 1
            page = max(1, page)

        stats = get_library_collection_stats()
        on_shelf = int(stats.get("on_shelf") or 0)
        max_page = max(1, (on_shelf + ps - 1) // ps) if on_shelf else 1
        if page > max_page:
            page = max_page

        raw_rows = list_on_shelf_overview_page(page, ps)
        if not raw_rows and on_shelf == 0:
            dispatcher.utter_message(text="当前演示库暂无可展示的在架书目，请稍后重试。")
            return []

        payload_rows = [
            {
                "book_title": (r.get("lib_book") or "").strip(),
                "call_number": (r.get("book_key") or "").strip(),
                "book_pos": ((r.get("book_pos") or "").strip() or "位置未定"),
                "book_summary": (str(r.get("summary") or "").strip()[:260]),
            }
            for r in raw_rows
        ]

        anchor_idx = (page - 1) * ps
        has_prev = page > 1
        has_more = anchor_idx + len(raw_rows) < on_shelf

        tgt = str(oc.get("target_message_id") or "").strip()
        foot = (
            "可说「**推荐阅读**」「**借书**」「**书籍总览**」等，系统按整句识别，**不是只能报书名**。"
        )

        payload: Dict[Text, Any] = {
            "payload_type": "overview_catalog",
            "stats": {
                "total": int(stats.get("total") or 0),
                "on_shelf": on_shelf,
                "borrowed": int(stats.get("borrowed") or 0),
            },
            "page": page,
            "page_size": ps,
            "on_shelf_total": on_shelf,
            "has_prev": has_prev,
            "has_more": has_more,
            "rows": payload_rows,
            "footnote": foot,
            "target_message_id": tgt,
            "mode": "replace_page" if tgt else "initial",
        }

        intro = ""
        if intent_name == "book_overview" and not tgt:
            intro = (
                "### 书籍总览（演示库）\n\n"
                f"馆藏 **{stats['total']}** 本 · 在架可借 **{on_shelf}** 本 · 已借出 **{stats['borrowed']}** 本。\n\n"
                "下面为 **在架书目**（按索书号排序，**每次只从数据库加载本页**；翻页时再次查询）。"
            )

        dispatcher.utter_message(text=intro, json_message=payload)
        return []


_BOOK_INTRO_DEEPSEEK_SYSTEM = (
    "你是高校图书馆智能助手的「导读」撰稿人。\n"
    "用户想了解某本书。你会收到 JSON：**library_book** 与 **alternate_call_numbers** 来自 Neo4j 演示库；"
    "**graph_record** 为书目图谱中与该书尽量匹配的一条（可能为空）。\n"
    "写作要求：\n"
    "1) 优先依据 JSON 中的书名、索书号、架位、流通状态、馆藏简介及图谱字段；**不要编造** JSON 未出现的索书号、架位与借阅状态。\n"
    "2) 若馆藏简介已较完整，可做条理化解说；可补充通识性阅读建议，并标明为「一般性背景」而非馆藏事实。\n"
    "3) 篇幅约 220–450 字，使用 Markdown（可加二级小标题）。\n"
    "4) 结尾简短提醒：流通状态以馆藏书目为准；办理借还可说「借书」或「还书」。\n"
)


def _strip_book_intro_command(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    cut = t
    for phrase in (
        "介绍一下这本书",
        "介绍一下这本",
        "介绍一下",
        "帮我介绍",
        "给我介绍",
        "介绍这本书",
        "介绍这本",
        "说说这本书",
        "说说这本",
        "说说",
        "讲讲这本书",
        "讲讲",
        "讲一下这本书",
        "讲一下",
        "聊聊这本书",
        "聊聊",
        "科普一下",
        "评价一下",
        "什么是",
        "想了解",
    ):
        if cut.startswith(phrase):
            cut = cut[len(phrase) :].strip()
    for phrase in ("这本书", "这本", "咋样", "怎么样", "是啥", "好不好看", "值得读吗"):
        if cut.endswith(phrase):
            cut = cut[: -len(phrase)].strip()
    cut = cut.strip("《》""''\"「」").strip()
    return cut


def _first_kg_call_number(text: str) -> str:
    m = re.search(r"(KG\.[A-Z0-9.]+)", (text or "").upper())
    return m.group(1) if m else ""


def _compact_graph_for_intro(gr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not gr or not isinstance(gr, dict):
        return {}
    sm = str(gr.get("summary") or "").strip()
    return {
        "title": (str(gr.get("title") or "").strip()) or None,
        "book_key": (str(gr.get("book_key") or "").strip()) or None,
        "rating": gr.get("rating"),
        "summary": (sm[:1500] + "…") if len(sm) > 1500 else sm,
        "authors": gr.get("authors"),
        "topics": gr.get("topics"),
        "categories": gr.get("categories"),
    }


def _resolve_book_intro_row(tracker: Tracker) -> Tuple[Optional[Dict[str, Any]], str]:
    text = (tracker.latest_message.get("text") or "").strip()
    call_guess = _first_kg_call_number(text)
    if call_guess:
        row = get_library_book_by_call_number(call_guess)
        if row:
            return row, text
    for ent in tracker.latest_message.get("entities") or []:
        if ent.get("entity") == "book_title":
            raw = (ent.get("value") or ent.get("text") or "").strip()
            if raw:
                q = _normalize_title_from_text(raw)
                if q:
                    rows = search_library_books_for_intro(q, limit=8)
                    if rows:
                        return rows[0], text
    stripped = _strip_book_intro_command(text)
    if stripped:
        q2 = _normalize_title_from_text(stripped)
        if q2:
            rows2 = search_library_books_for_intro(q2, limit=8)
            if rows2:
                return rows2[0], text
    remembered = (tracker.get_slot("last_recommended_title") or "").strip()
    if remembered and _is_demo_book_reference(text):
        rows3 = search_library_books_for_intro(remembered, limit=4)
        if rows3:
            return rows3[0], text
    return None, text


class ActionBookIntroduce(Action):
    """单书介绍：Neo4j 事实 + 可选图谱片段，交由 DeepSeek 写导读。"""

    def name(self) -> Text:
        return "action_book_introduce"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        row, user_text = _resolve_book_intro_row(tracker)
        if not row:
            dispatcher.utter_message(
                text=(
                    "请直接说**书名**（或《…》书名号）、也可以说**索书号**（如 KG.GR.00001）；"
                    "也可先说「推荐阅读」「书籍总览」再选书。"
                )
            )
            return []

        lib_book = (row.get("lib_book") or "").strip()
        book_key = (row.get("book_key") or "").strip()
        if not lib_book or not book_key:
            dispatcher.utter_message(text="未能从演示库解析到完整书目字段，请换关键词或索书号再试。")
            return []

        others = [
            r
            for r in search_library_books_for_intro(lib_book, limit=8)
            if (r.get("book_key") or "").strip() and (r.get("book_key") or "").strip().upper() != book_key.upper()
        ]

        graph_rows = neo4j_recommend_by_topic(lib_book, limit=16)
        graph_pick: Optional[Dict[str, Any]] = None
        for gr in graph_rows:
            gk = str(gr.get("book_key") or "").strip().upper()
            gt = str(gr.get("title") or "").strip()
            if gk == book_key.upper() or (lib_book and gt == lib_book):
                graph_pick = gr
                break

        facts: Dict[str, Any] = {
            "user_utterance": user_text,
            "library_book": {
                "lib_book": lib_book,
                "book_key": book_key,
                "book_pos": (str(row.get("book_pos") or "").strip() or "位置未定"),
                "circulation": _circulation_label(row),
                "summary_from_catalog": (str(row.get("summary") or "").strip())[:1200],
            },
            "alternate_call_numbers": [
                (r.get("book_key") or "").strip() for r in others if (r.get("book_key") or "").strip()
            ][:5],
            "graph_record": _compact_graph_for_intro(graph_pick),
        }

        ds_flag = (os.environ.get("BOOK_INTRO_DEEPSEEK") or os.environ.get("READING_RECOMMEND_DEEPSEEK") or "1").strip().lower()
        told = False
        if ds_flag not in ("0", "false", "off", "no"):
            user_blob = json.dumps(facts, ensure_ascii=False, indent=2) + "\n\n请根据以上 JSON 撰写导读/介绍。"
            ds_text, ds_err = deepseek_chat(
                user_blob,
                system=_BOOK_INTRO_DEEPSEEK_SYSTEM,
                timeout=55.0,
                temperature=0.42,
            )
            if ds_text and ds_text.strip():
                dispatcher.utter_message(text=ds_text.strip())
                told = True
            elif ds_err and ds_err != "missing_api_key":
                logging.getLogger(__name__).info("book_intro DeepSeek 跳过: %s", ds_err)

        if not told:
            pos = (str(row.get("book_pos") or "").strip() or "位置未定")
            sm = (str(row.get("summary") or "").strip()) or "（演示库暂无简介文本）"
            dispatcher.utter_message(
                text=(
                    f"**《{lib_book}》**（索书号 `{book_key}`，架位 {pos}，{_circulation_label(row)}）\n\n"
                    f"**馆藏摘要**：{sm}\n\n"
                    "（DeepSeek 未启用或调用失败，仅展示数据库摘要。配置 `DEEPSEEK_API_KEY` 后可生成导读。）"
                )
            )

        return [
            SlotSet("last_recommended_title", lib_book),
            SlotSet("last_recommended_call_number", book_key),
        ]


class ActionBorrowRecordQuery(Action):
    def name(self) -> Text:
        return "action_borrow_record_query"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        text = (tracker.latest_message.get("text") or "").strip()
        metadata = tracker.latest_message.get("metadata") or {}
        borrower_id = ""
        if isinstance(metadata, dict):
            borrower_id = str(metadata.get("borrower_id") or "").strip()
        if not borrower_id:
            m = re.search(r"\d{6,20}", text)
            if m:
                borrower_id = m.group(0)
        if not borrower_id:
            borrower_id = (tracker.sender_id or "").strip()
        rows = list_borrow_records(borrower_id, limit=20)
        if not rows:
            dispatcher.utter_message(
                text=f"未查询到账号 {borrower_id} 的借阅记录。可说“借阅记录 20230001”按学号/手机号查询。"
            )
            return []
        active_count = sum(1 for r in rows if not (r.get("returned_at") or "").strip())
        lines = []
        for i, r in enumerate(rows[:10], start=1):
            returned_at = (r.get("returned_at") or "").strip()
            status = f"已归还（{returned_at}）" if returned_at else "未归还"
            lines.append(
                f"{i}. 《{r['lib_book']}》 {r['book_key']} | 借出:{r['borrow_at']} | 预计还:{r['due_at']} | {status}"
            )
        dispatcher.utter_message(
            text=f"借阅记录（账号 {borrower_id}）：未归还 {active_count}/3 本。\n" + "\n".join(lines)
        )
        return []


class ActionDataInquiry(Action):
    """数据类咨询：意图覆盖检索 + Rasa 次优意图 + DeepSeek 综合生成；失败时回退固定话术。"""

    def name(self) -> Text:
        return "action_data_inquiry"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        user_text = (tracker.latest_message.get("text") or "").strip()
        if not user_text:
            dispatcher.utter_message(response="utter_data_inquiry")
            return []

        kb_scored = score_kb_entries(user_text)
        nlu_signals = nlu_intent_signals(tracker.latest_message)
        payload = build_deepseek_user_payload(user_text, kb_scored, nlu_signals)
        system = _deepseek_multi_intent_system()
        if graph_rag_enabled():
            evidence, _gerr = graph_rag_retrieve_evidence(user_text)
            if evidence:
                payload += (
                    "\n\n【Neo4j 图谱检索结果（GraphRAG，只读；JSON 数组）】\n"
                    + evidence
                    + "\n\n若上述 JSON 与用户问题相关，请优先依据其中的书名、作者、主题、类目、rating、summary 等字段回答；"
                    "不要编造 JSON 未出现的书目。若不相关或无把握，则说明并回到一般性方法与 OPAC 引导。"
                )
                system += (
                    "\n\n当前轮次已附加 Neo4j 书目图谱只读检索结果；涉及具体图书目录关系时请引用该片段，无法覆盖则说明限制。"
                )
        content, _err = deepseek_chat(payload, system=system)
        if not content:
            dispatcher.utter_message(response="utter_data_inquiry")
            return []

        suffix = "（以上内容由大模型生成；演示环境无接入实时统计，请勿作为官方数据依据。）"
        dispatcher.utter_message(text=f"{content}\n\n{suffix}")
        return []


class ActionNluFallbackRouter(Action):
    """
    nlu_fallback：仅对「多主题/复合问」走意图覆盖 + DeepSeek；其余仍 utter_default。
    不替代借还书表单与业务 actions。
    """

    def name(self) -> Text:
        return "action_nlu_fallback_router"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        user_text = (tracker.latest_message.get("text") or "").strip()
        if not user_text:
            dispatcher.utter_message(response="utter_default")
            return []

        kb_scored = score_kb_entries(user_text)
        nlu_signals = nlu_intent_signals(tracker.latest_message)
        if not should_treat_as_compound_fallback(user_text, kb_scored, nlu_signals):
            dispatcher.utter_message(response="utter_default")
            return []

        payload = build_deepseek_user_payload(user_text, kb_scored, nlu_signals)
        system = _deepseek_multi_intent_system()
        if graph_rag_enabled():
            evidence, _gerr = graph_rag_retrieve_evidence(user_text)
            if evidence:
                payload += (
                    "\n\n【Neo4j 图谱检索结果（GraphRAG，只读；JSON 数组）】\n"
                    + evidence
                    + "\n\n若上述 JSON 与用户问题相关，请优先依据其中的书名、作者、主题、类目、rating、summary 等字段回答；"
                    "不要编造 JSON 未出现的书目。"
                )
                system += (
                    "\n\n当前轮次已附加 Neo4j 书目图谱只读检索结果；涉及图书目录关系时请引用该片段。"
                )
        content, _err = deepseek_chat(payload, system=system)
        if not content:
            dispatcher.utter_message(response="utter_default")
            return []

        suffix = "（以上内容由大模型生成；演示环境无接入实时统计，请勿作为官方数据依据。）"
        dispatcher.utter_message(text=f"{content}\n\n{suffix}")
        return []
