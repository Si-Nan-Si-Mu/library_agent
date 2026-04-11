"""馆藏书目 SQLite：默认库文件在 backend/data/library.db，可用环境变量 LIBRARY_SQLITE_PATH 覆盖。"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS library_book (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_key TEXT NOT NULL UNIQUE,
    lib_book TEXT NOT NULL,
    book_pos TEXT,
    is_borrow INTEGER NOT NULL DEFAULT 0 CHECK (is_borrow IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_library_book_is_borrow ON library_book (is_borrow);
CREATE INDEX IF NOT EXISTS idx_library_book_lib_book ON library_book (lib_book);
"""

_SEED_ROWS: List[Tuple[str, str, str, int]] = [
    ("B-HLM-001", "红楼梦（人民文学）", "文学库 A-01", 0),
    ("B-XYJ-002", "西游记（人民文学）", "文学库 A-02", 1),
    ("TP311.5/PY-01", "Python 程序设计", "科技库 T-03", 0),
    ("TP311/DL-01", "深度学习入门", "科技库 T-05", 0),
    ("I247.5/XX-01", "平凡的世界", "文学库 B-10", 0),
]


def _default_db_path() -> Path:
    override = os.environ.get("LIBRARY_SQLITE_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "data" / "library.db"


def db_path() -> Path:
    return _default_db_path()


def get_connection() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    cur = conn.execute("SELECT COUNT(1) FROM library_book")
    if cur.fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO library_book (book_key, lib_book, book_pos, is_borrow) VALUES (?,?,?,?)",
            _SEED_ROWS,
        )
        conn.commit()
    else:
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def find_in_library_row(
    conn: sqlite3.Connection, title: str, call_no: str, borrowed: int
) -> Optional[sqlite3.Row]:
    title = (title or "").strip()
    call_no = (call_no or "").strip()
    cur = conn.cursor()
    if call_no:
        cur.execute(
            "SELECT * FROM library_book WHERE book_key = ? AND is_borrow = ? LIMIT 1",
            (call_no, borrowed),
        )
        row = cur.fetchone()
        if row:
            return row
    if title:
        cur.execute(
            "SELECT * FROM library_book WHERE lib_book LIKE ? AND is_borrow = ? LIMIT 1",
            (f"%{title}%", borrowed),
        )
        row = cur.fetchone()
        if row:
            return row
    if call_no:
        cur.execute(
            "SELECT * FROM library_book WHERE book_key LIKE ? AND is_borrow = ? LIMIT 1",
            (f"%{call_no}%", borrowed),
        )
        row = cur.fetchone()
        if row:
            return row
    return None


def borrow_book(title: str, call_no: str) -> Tuple[bool, Optional[dict]]:
    """在馆则可借：更新 is_borrow=1。返回 (是否成功, 书目信息或 None)。"""
    try:
        with get_connection() as conn:
            row = find_in_library_row(conn, title, call_no, 0)
            if not row:
                return False, None
            conn.execute(
                "UPDATE library_book SET is_borrow = 1, updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            info = _row_to_dict(row)
            info["is_borrow"] = 1
            return True, info
    except sqlite3.Error as e:
        logger.warning("SQLite borrow_book: %s", e)
        return False, None


def return_book(title: str, call_no: str) -> Tuple[bool, Optional[dict]]:
    """已借出则可还：更新 is_borrow=0。"""
    try:
        with get_connection() as conn:
            row = find_in_library_row(conn, title, call_no, 1)
            if not row:
                return False, None
            conn.execute(
                "UPDATE library_book SET is_borrow = 0, updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            info = _row_to_dict(row)
            info["is_borrow"] = 0
            return True, info
    except sqlite3.Error as e:
        logger.warning("SQLite return_book: %s", e)
        return False, None


def recommend_on_shelf(topic: Optional[str], limit: int = 5) -> List[dict]:
    """按正题名模糊匹配在架图书。"""
    topic = (topic or "").strip()
    if not topic:
        return []
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT book_key, lib_book, book_pos
                FROM library_book
                WHERE is_borrow = 0 AND lib_book LIKE ?
                ORDER BY lib_book
                LIMIT ?
                """,
                (f"%{topic}%", limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        logger.warning("SQLite recommend_on_shelf: %s", e)
        return []
