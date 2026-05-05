#!/usr/bin/env python3
"""
从 CrossWOZ 用户话轮 jsonl 中按启发式分桶，导出「待人工改写」候选句，便于写入 Rasa nlu.yml。

输入：backend/data/crosswoz/user_utterances_train.jsonl
输出：backend/data/crosswoz/candidates/*.txt + README.md

注意：分桶仅作参考，领域与图书馆不对齐，请勿未经改写整段导入训练数据。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def load_lines(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("text"):
                yield obj


def act_tuples(rec: Dict[str, Any]) -> List[Tuple[str, str]]:
    """CrossWOZ 单条 act 为 [类型, 领域, 槽, 值]；类型为 General 时第二项为 greet/thank/bye。"""
    raw = rec.get("dialog_act") or []
    out: List[Tuple[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, list) or len(item) < 2:
            continue
        out.append((str(item[0]), str(item[1])))
    return out


def has_general(acts_list: List[Tuple[str, str]], name: str) -> bool:
    return any(a[0] == "General" and a[1] == name for a in acts_list)


def any_slot_domain(acts_list: List[Tuple[str, str]], domains: Set[str]) -> bool:
    """Inform/Request/Select 等领域在第二段。"""
    return any(a[0] in {"Inform", "Request", "Select"} and a[1] in domains for a in acts_list)


def act_types(acts_list: List[Tuple[str, str]]) -> Set[str]:
    return {a[0] for a in acts_list}


def bucket_for(rec: Dict[str, Any]) -> Optional[str]:
    text = (rec.get("text") or "").strip()
    if not text:
        return None
    a = act_tuples(rec)
    types = act_types(a)

    # 优先匹配更「窄」的句式，避免首句问候抢走「推荐/查询」类样本
    if re.search(r"^(好|行|可以|嗯|对|好的|没问题|OK|ok)[，。!！…\s]*$", text) and len(text) <= 12:
        return "07_short_affirm"

    if re.search(r"^(不|不要|不用|算了|取消|先不)", text) or re.search(
        r"(不用了|不要了|先这样吧|先不(要|借|还)了)", text
    ):
        return "08_short_deny"

    if any_slot_domain(a, {"地铁", "出租"}):
        return "09_metro_taxi"

    if re.search(r"你能(帮|给)?我|你会(做|查)|可以帮我|有什么功能|怎么用", text):
        return "06_ask_capabilities"

    if "推荐" in text or re.search(r"有什么好的建议|给?我介绍", text):
        return "04_reading_recommend"

    if has_general(a, "greet"):
        return "01_greet"
    if has_general(a, "bye"):
        return "02_goodbye"
    if has_general(a, "thank") and not has_general(a, "bye"):
        if re.search(r"没有|没了|不问了|先到这|先这样|没问题了", text):
            return "02_goodbye"
        return "03_thanks_only"

    if "Request" in types or "Select" in types:
        return "05_request_inform_query"

    if re.search(r"(总共|一共|有哪些|列出|书目|馆藏)", text):
        return "10_book_overview_hint"

    return None


def dedupe_add(store: Dict[str, Set[str]], bucket: str, text: str, cap: int, buckets: Dict[str, List[str]]) -> None:
    if bucket not in store:
        store[bucket] = set()
    if text in store[bucket]:
        return
    if len(buckets[bucket]) >= cap:
        return
    store[bucket].add(text)
    buckets[bucket].append(text)


def write_readme(out_dir: Path) -> None:
    content = """# CrossWOZ 导出候选（待人工改写）

由 `scripts/crosswoz_nlu_candidates.py` 从 `user_utterances_train.jsonl` 抽样生成。**不要**未改写整段合并进 `nlu.yml`。

## 分桶与建议对应关系（仅供参考）

| 文件前缀 | 建议映射到 Rasa intent | 说明 |
|----------|------------------------|------|
| 01_greet | `greet` | 含 `General/greet` |
| 02_goodbye | `goodbye` | 含 `General/bye` 或结束会话类感谢 |
| 03_thanks_only | `goodbye` 或删除 | 纯感谢；可改写成「谢谢，先结束」或丢弃 |
| 04_reading_recommend | `reading_recommend` | 含「推荐」等；改写成图书推荐说法 |
| 05_request_inform_query | `borrow_book` / `return_book` / `borrow_record_query` | Inform+Request 查询风格；改成借书/还书/查记录 |
| 06_ask_capabilities | `ask_capabilities` | 「你能…吗」类 |
| 07_short_affirm | `affirm` | 极短肯定（易与其它混淆，请精挑） |
| 08_short_deny | `deny` | 否定/取消开头 |
| 09_metro_taxi | `space_booking` 或 `borrow_guide` | 地铁/出租域；可改成预约/问路说法或丢弃 |
| 10_book_overview_hint | `book_overview` | 含「有哪些/总共」等；可改成馆藏总览说法 |

改写后请删除实体地名/店名，换成书名或「这本书」等图书馆语境，再写入 `backend/data/nlu.yml`。
"""
    (out_dir / "README.md").write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        type=Path,
        default=Path("backend/data/crosswoz/user_utterances_train.jsonl"),
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backend/data/crosswoz/candidates"),
    )
    ap.add_argument("--per-bucket", type=int, default=120, help="每桶最多条数（去重后）")
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"找不到输入: {args.input}", file=sys.stderr)
        return 1

    order = [
        "01_greet",
        "02_goodbye",
        "03_thanks_only",
        "04_reading_recommend",
        "05_request_inform_query",
        "06_ask_capabilities",
        "07_short_affirm",
        "08_short_deny",
        "09_metro_taxi",
        "10_book_overview_hint",
    ]
    buckets: Dict[str, List[str]] = {k: [] for k in order}
    seen: Dict[str, Set[str]] = {}

    for rec in load_lines(args.input):
        b = bucket_for(rec)
        if b is None or b not in buckets:
            continue
        text = (rec.get("text") or "").strip()
        dedupe_add(seen, b, text, args.per_bucket, buckets)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for key in order:
        path = args.output_dir / f"{key}.txt"
        path.write_text("\n".join(buckets[key]) + ("\n" if buckets[key] else ""), encoding="utf-8", newline="\n")
        print(f"{key}: {len(buckets[key])} -> {path}", file=sys.stderr)

    write_readme(args.output_dir)
    print(f"Wrote {args.output_dir / 'README.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
