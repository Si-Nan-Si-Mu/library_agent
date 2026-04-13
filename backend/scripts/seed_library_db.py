"""
触发馆藏书目 SQLite 初始化与补全（保证 ≥120 条）。

在 backend 目录执行：
  set PYTHONPATH=.
  python scripts/seed_library_db.py

或删除 data/library.db 后首次启动 Action 也会自动建表并填充。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 保证可从 backend 根目录导入 actions
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from actions.library_db import db_path, get_connection  # noqa: E402


def main() -> None:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(1) FROM library_book").fetchone()[0]
    conn.close()
    print(f"library_book 行数: {n}，库文件: {db_path()}")


if __name__ == "__main__":
    main()
