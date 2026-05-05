"""
意图覆盖（启发式）+ 检索片段：从固定知识库匹配关键词，供 DeepSeek 提示词使用。
不替代 Rasa NLU；借还书实际流程仍由表单与 actions 处理。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_KB_PATH = Path(__file__).resolve().parent.parent / "data" / "intent_retrieval_kb.json"

_COMPOUND_CONNECTORS = re.compile(
    r"(还有|另外|顺便|同时|以及|再问|又想|既要|也要|不光|不仅|除了|一是|二是|第一|第二)"
)


@lru_cache(maxsize=1)
def _load_kb_raw() -> Dict[str, Any]:
    if not _KB_PATH.is_file():
        return {"entries": [], "borrow_policy_anchor": ""}
    with _KB_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def score_kb_entries(user_text: str) -> List[Dict[str, Any]]:
    """按关键词命中次数为每条 KB 条目打分（同一用户话可命中多条）。"""
    text = (user_text or "").strip()
    if not text:
        return []
    raw = _load_kb_raw()
    entries = raw.get("entries") or []
    out: List[Dict[str, Any]] = []
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        eid = str(ent.get("id") or "").strip()
        kws = ent.get("keywords") or []
        if not eid or not isinstance(kws, list):
            continue
        hits = [k for k in kws if isinstance(k, str) and k and k in text]
        score = len(hits)
        if score:
            out.append(
                {
                    "id": eid,
                    "score": min(score, 6),
                    "keyword_hits": hits[:8],
                    "summary": str(ent.get("summary") or "").strip(),
                }
            )
    out.sort(key=lambda x: (-x["score"], x["id"]))
    return out


def nlu_intent_signals(latest_message: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """读取 Rasa 解析的 intent_ranking，作为次要意图参考。"""
    if not isinstance(latest_message, dict):
        return []
    ranking = latest_message.get("intent_ranking")
    if not isinstance(ranking, list):
        return []
    out = []
    for item in ranking[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name == "nlu_fallback":
            continue
        try:
            conf = float(item.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf >= 0.08:
            out.append({"name": name, "confidence": round(conf, 4)})
    return out


def should_treat_as_compound_fallback(
    user_text: str,
    kb_scored: List[Dict[str, Any]],
    nlu_signals: List[Dict[str, Any]],
) -> bool:
    """
    无表单时的 nlu_fallback：仅对「像多主题长问句」走 DeepSeek，短句仍 utter_default。
    """
    text = (user_text or "").strip()
    if len(text) < 14:
        return False

    strong_kb = [x for x in kb_scored if x.get("score", 0) >= 2]
    any_kb = [x for x in kb_scored if x.get("score", 0) >= 1]

    if len(strong_kb) >= 2:
        return True
    if len(any_kb) >= 2:
        return True
    if _COMPOUND_CONNECTORS.search(text) and len(any_kb) >= 1:
        return True

    # NLU 对 fallback 仍可能给出次高意图
    if len(nlu_signals) >= 2 and nlu_signals[1].get("confidence", 0) >= 0.12:
        return True

    return False


def build_retrieval_context(kb_scored: List[Dict[str, Any]], max_snippets: int = 6) -> str:
    lines: List[str] = []
    for ent in kb_scored[:max_snippets]:
        sid = ent.get("id")
        summ = ent.get("summary") or ""
        hits = ent.get("keyword_hits") or []
        if not summ:
            continue
        hit_s = "、".join(hits[:6]) if hits else ""
        lines.append(f"- [{sid}]（命中：{hit_s}）{summ}")
    return "\n".join(lines) if lines else "（未命中预设关键词，请仅根据用户话与馆方常识谨慎作答。）"


def build_deepseek_user_payload(
    user_text: str,
    kb_scored: List[Dict[str, Any]],
    nlu_signals: List[Dict[str, Any]],
) -> str:
    """组装发给 DeepSeek 的 user 侧结构化说明（非用户原话替换）。"""
    cov_lines = []
    for ent in kb_scored[:10]:
        cov_lines.append(
            f"- {ent.get('id')}（score={ent.get('score')}，关键词："
            f"{'、'.join((ent.get('keyword_hits') or [])[:6])}）"
        )
    cov_block = "\n".join(cov_lines) if cov_lines else "- （无关键词命中）"

    nlu_lines = [f"- {x['name']}（confidence={x['confidence']}）" for x in nlu_signals[:5]]
    nlu_block = "\n".join(nlu_lines) if nlu_lines else "- （无有效 intent_ranking）"

    retrieval = build_retrieval_context(kb_scored)

    return (
        "请根据以下「分析」与「检索摘要」回答用户；用户原话在最后一行。\n\n"
        f"【用户原话】\n{user_text}\n\n"
        f"【意图覆盖（关键词启发式，可多标签）】\n{cov_block}\n\n"
        f"【Rasa NLU 意图排序（参考，可能含 nlu_fallback）】\n{nlu_block}\n\n"
        f"【检索到的业务摘要（演示环境，勿当官方规章全文）】\n{retrieval}\n\n"
        "请分点组织答案；不要编造具体统计数字与精确开馆时刻；"
        "涉及借书、还书「办理」时只引导用户在本对话中说「借书」或「还书」，不要声称已代为办理。"
    )


def borrow_policy_anchor() -> str:
    raw = _load_kb_raw()
    return str(raw.get("borrow_policy_anchor") or "").strip()
