import json
import re
from typing import Any, Text, Dict, List, Optional

try:
    from kg_module.env_bootstrap import load_repo_dotenv

    load_repo_dotenv()
except Exception:
    pass

from .library_db import (
    borrow_book,
    format_on_shelf_borrow_preview,
    get_active_borrow_count,
    get_catalog_overview,
    list_active_borrow_records,
    list_catalog_books,
    list_borrow_records,
    list_borrowed_by_title,
    list_on_shelf_by_title,
    lookup_circulation,
    record_borrow_transaction,
    recommend_on_shelf,
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
from .neo4j_graph import recommend_books_by_topic as neo4j_recommend_by_topic

_DATA_INQUIRY_SYSTEM = (
    "你是高校图书馆智能助手（演示环境）。用户会做开放数据、统计口径、借阅趋势类、推荐阅读等类别的提问。"
    "你只提供一般性方法、概念说明与合规注意点；不得编造具体的借阅量、百分比、排名等数字。"
    "若需要精确数据，应引导对方通过馆方 OPAC、报表系统或经授权的统计服务查询，并提及权限与审计要求。"
    "或者使用sql语句查询图书馆的sqlite数据库，然后根据查询结果回答用户的问题。"
    "回答使用用户相对熟悉的语言，条理清晰，篇幅适中。"
    "不要使用任何括号表示情绪或动作。"
)


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
                    "status": "已借出" if borrowed else "在架可借",
                    "is_available": not borrowed,
                }
            )
        dispatcher.utter_message(text="请问要办理的书名是？可在下方书目表中搜索并翻页选择。")
        dispatcher.utter_message(
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
            }
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
        topic = (tracker.get_slot("topic") or "").strip()
        if topic:
            graph_rows = neo4j_recommend_by_topic(topic, limit=8)
            if graph_rows:
                lines = []
                for r in graph_rows:
                    rating = r.get("rating")
                    rate_s = f"{rating}" if rating is not None else "-"
                    sm = (r.get("summary") or "").strip()
                    extra = f" — {sm}" if sm else ""
                    lines.append(f"《{r['title']}》（评分 {rate_s}）{extra}")
                dispatcher.utter_message(
                    text=(
                        f"根据知识图谱（Neo4j）与主题「{topic}」的匹配结果（演示数据）：\n"
                        + "\n".join(lines)
                        + "\n可直接回复「借这本」或书名继续办理借阅。具体以 OPAC 与正式馆藏目录为准。"
                    )
                )
                top = graph_rows[0]
                return [
                    SlotSet("last_recommended_title", (top.get("title") or "").strip() or None),
                    SlotSet("last_recommended_call_number", (top.get("book_key") or "").strip() or None),
                    SlotSet(
                        "last_recommended_candidates",
                        json.dumps([str(x.get("title") or "").strip() for x in graph_rows if str(x.get("title") or "").strip()], ensure_ascii=False),
                    ),
                ]

        rows = recommend_on_shelf(topic or None)
        if topic and rows:
            lines = [
                f"《{r['lib_book']}》 — {r['book_pos'] or '位置未定'} （{r['book_key']}）"
                for r in rows
            ]
            dispatcher.utter_message(
                text=(
                    f"与「{topic}」匹配的在架书目（SQLite 演示库，仅供参考）：\n"
                    + "\n".join(lines)
                    + "\n可直接回复「借这本」或书名继续办理借阅。具体以 OPAC 为准。"
                )
            )
            top = rows[0]
            return [
                SlotSet("last_recommended_title", top["lib_book"]),
                SlotSet("last_recommended_call_number", top["book_key"]),
                SlotSet(
                    "last_recommended_candidates",
                    json.dumps([str(x["lib_book"]).strip() for x in rows if str(x["lib_book"]).strip()], ensure_ascii=False),
                ),
            ]
        elif topic:
            dispatcher.utter_message(
                text=(
                    f"演示库中暂无题名含「{topic}」的在架图书，可换一个关键词；"
                    "也可检索同类目新书区与主题书架。"
                )
            )
            return [
                SlotSet("last_recommended_title", None),
                SlotSet("last_recommended_call_number", None),
                SlotSet("last_recommended_candidates", None),
            ]
        else:
            dispatcher.utter_message(
                text=(
                    "推荐阅读（演示）：请告诉我感兴趣的主题，例如「历史」「人工智能」「文学」；"
                    "正式环境可对接推荐服务或热门借阅榜。"
                )
            )
            return []


class ActionBookOverview(Action):
    def name(self) -> Text:
        return "action_book_overview"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        overview = get_catalog_overview(limit=12)
        rows = overview.get("rows") or []
        if not rows:
            dispatcher.utter_message(text="当前演示库暂无可展示的在架书目，请稍后重试。")
            return []
        lines = [
            f"{i}. 《{r['lib_book']}》 — {r.get('book_pos') or '位置未定'}（{r['book_key']}）"
            for i, r in enumerate(rows, start=1)
        ]
        dispatcher.utter_message(
            text=(
                f"书籍总览（演示库）：共 {overview['total']} 本，在架可借 {overview['on_shelf']} 本，"
                f"已借出 {overview['borrowed']} 本。\n"
                "以下为部分在架书目：\n"
                + "\n".join(lines)
                + "\n如需按主题筛选，可继续说「推荐历史书」；如需借阅可直接说书名。"
            )
        )
        return []


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
    """数据类咨询：优先调用 DeepSeek 生成说明；未配置密钥或调用失败时回退到固定话术。"""

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

        content, _err = deepseek_chat(user_text, system=_DATA_INQUIRY_SYSTEM)
        if not content:
            dispatcher.utter_message(response="utter_data_inquiry")
            return []

        suffix = "（以上内容由大模型生成；演示环境无接入实时统计，请勿作为官方数据依据。）"
        dispatcher.utter_message(text=f"{content}\n\n{suffix}")
        return []
