import re
from typing import Any, Text, Dict, List, Optional

from .library_db import (
    borrow_book,
    format_on_shelf_borrow_preview,
    get_catalog_overview,
    list_borrowed_by_title,
    list_on_shelf_by_title,
    lookup_circulation,
    recommend_on_shelf,
    return_book,
)

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, AllSlotsReset, ActiveLoop
from rasa_sdk.forms import FormValidationAction


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
        title = _normalize_title_from_text(slot_value) if slot_value else ""
        if title:
            return {"book_title": title}
        latest = _normalize_title_from_text(tracker.latest_message.get("text"))
        if not latest:
            return {"book_title": None}
        rows = list_on_shelf_by_title(latest, limit=1)
        if rows:
            return {"book_title": rows[0]["lib_book"]}
        return {"book_title": latest}


class ActionBorrowBookFormSubmit(Action):
    def name(self) -> Text:
        return "action_borrow_book_form_submit"

    def run(self, dispatcher, tracker, domain):
        title = (tracker.get_slot("book_title") or "").strip()
        rows = list_on_shelf_by_title(title)
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
            ]

        if len(rows) == 1:
            r = rows[0]
            call_no = (r.get("book_key") or "").strip()
            dispatcher.utter_message(
                text=(
                    f"在架可借（1 本）：《{r['lib_book']}》 索书号 {r['book_key']}，"
                    f"架位 {r.get('book_pos') or '未定'}。"
                )
            )
            dispatcher.utter_message(text=format_on_shelf_borrow_preview(r))
            dispatcher.utter_message(
                text=f"确认借阅《{r['lib_book']}》（索书号 {call_no}）吗？"
            )
            return [
                SlotSet("borrow_phase", "single_confirm"),
                SlotSet("defer_nlu_fallback", False),
                SlotSet("call_number", call_no),
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
        raw = _normalize_call_input(raw)
        title = (tracker.get_slot("book_title") or "").strip()
        if not raw:
            dispatcher.utter_message(text="请回复列表中的索书号，或直接回复序号（如「1」「第2本」）。")
            return {"call_number": None}
        rows = list_on_shelf_by_title(title)
        picked = _pick_call_number(raw, rows)
        if picked:
            return {"call_number": picked}
        dispatcher.utter_message(
            text="该输入不在当前可借列表中，或对应副本已不在架。请回复列表中的索书号或序号。"
        )
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
        rows = list_on_shelf_by_title(title)
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
            ]
        dispatcher.utter_message(text=format_on_shelf_borrow_preview(row))
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
        ok, _, detail = borrow_book(title, call_no)
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
        raw = _normalize_call_input(raw)
        title = (tracker.get_slot("book_title") or "").strip()
        if not raw:
            dispatcher.utter_message(text="请回复列表中的索书号，或直接回复序号（如「1」「第2条」）。")
            return {"call_number": None}
        rows = list_borrowed_by_title(title)
        picked = _pick_call_number(raw, rows)
        if picked:
            return {"call_number": picked}
        dispatcher.utter_message(
            text="该输入不在当前待还列表中。请核对后重新输入列表中的索书号或序号。"
        )
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
        ok, _, detail = return_book(title, call_no)
        return [
            AllSlotsReset(),
            SlotSet("api_return_succeed", ok),
            SlotSet("last_return_detail", detail),
            ActiveLoop(None),
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
                    + "\n具体以 OPAC 为准。"
                )
            )
        elif topic:
            dispatcher.utter_message(
                text=(
                    f"演示库中暂无题名含「{topic}」的在架图书，可换一个关键词；"
                    "也可检索同类目新书区与主题书架。"
                )
            )
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
