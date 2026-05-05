#!/usr/bin/env python3
"""
从 CrossWOZ 官方 train.json 抽取「用户话轮 + dialog_act」，生成轻量 jsonl，供 Rasa 语料扩写/对齐参考。

原始数据：https://github.com/thu-coai/CrossWOZ （Apache-2.0）
完整 train.json 体积大，本仓库只保留抽样 jsonl；需要全量时请自行下载 train.json.zip 后调大 --max-lines。

用法:
  python scripts/build_crosswoz_user_utterances_sample.py \\
    --input path/to/train.json \\
    --output backend/data/crosswoz/user_utterances_train.jsonl \\
    --max-lines 12000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def iter_user_turns(data: Dict[str, Any]) -> Iterable[Tuple[str, List[Any]]]:
    for _task_id, dialog in data.items():
        if not isinstance(dialog, dict):
            continue
        for turn in dialog.get("messages") or []:
            if not isinstance(turn, dict):
                continue
            if turn.get("role") != "usr":
                continue
            text = (turn.get("content") or "").strip()
            if not text:
                continue
            acts = turn.get("dialog_act") or []
            if not isinstance(acts, list):
                acts = []
            yield text, acts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True, help="CrossWOZ train.json 路径")
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("backend/data/crosswoz/user_utterances_train.jsonl"),
        help="输出 jsonl",
    )
    ap.add_argument(
        "--max-lines",
        type=int,
        default=12_000,
        help="最多写入多少条用户话轮（控制仓库体积）",
    )
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"找不到输入文件: {args.input}", file=sys.stderr)
        return 1

    print("加载 JSON（体积较大时请耐心等待）…", file=sys.stderr)
    with args.input.open("r", encoding="utf-8") as f:
        data = json.load(f)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for text, acts in iter_user_turns(data):
            if n >= args.max_lines:
                break
            rec = {"text": text, "dialog_act": acts}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1

    print(f"已写入 {n} 条 -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
