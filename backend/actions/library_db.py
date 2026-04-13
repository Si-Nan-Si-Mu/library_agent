"""馆藏书目 SQLite：默认库文件在 backend/data/library.db，可用环境变量 LIBRARY_SQLITE_PATH 覆盖。"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple

from .book_catalog_seed import generate_bulk_rows, minimum_catalog_size

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
CREATE INDEX IF NOT EXISTS idx_library_book_book_key ON library_book (book_key);
"""

# 少量经典演示行（与早期种子一致）；其余由 book_catalog_seed 补至 MIN 条
_SEED_ROWS: List[Tuple[str, str, str, int]] = [
    ("B-HLM-001", "红楼梦（人民文学）", "文学库 A-01", 1),
    ("B-XYJ-002", "西游记（人民文学）", "文学库 A-02", 0),
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


def _ensure_row_count(conn: sqlite3.Connection) -> None:
    """保证演示库至少有 minimum_catalog_size() 条书目。"""
    min_n = minimum_catalog_size()
    cur = conn.execute("SELECT COUNT(1) FROM library_book")
    n = int(cur.fetchone()[0])
    if n >= min_n:
        return
    need = min_n - n
    bulk = generate_bulk_rows(need, key_offset=n)
    conn.executemany(
        "INSERT INTO library_book (book_key, lib_book, book_pos, is_borrow) VALUES (?,?,?,?)",
        bulk,
    )
    conn.commit()
    logger.info("Seeded %s library_book rows (total target >= %s).", need, min_n)


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
    _ensure_row_count(conn)


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def find_book_row_any(
    conn: sqlite3.Connection, title: str, call_no: str
) -> Optional[sqlite3.Row]:
    """按索书号/题名查找一条书目（不区分在架与否）。"""
    title = (title or "").strip()
    call_no = (call_no or "").strip()
    cur = conn.cursor()
    if call_no:
        cur.execute(
            "SELECT * FROM library_book WHERE book_key = ? LIMIT 1",
            (call_no,),
        )
        row = cur.fetchone()
        if row:
            return row
    if title:
        cur.execute(
            "SELECT * FROM library_book WHERE lib_book LIKE ? ORDER BY id LIMIT 1",
            (f"%{title}%",),
        )
        row = cur.fetchone()
        if row:
            return row
    if call_no:
        cur.execute(
            "SELECT * FROM library_book WHERE book_key LIKE ? ORDER BY id LIMIT 1",
            (f"%{call_no}%",),
        )
        row = cur.fetchone()
        if row:
            return row
    return None


def find_in_library_row(
    conn: sqlite3.Connection, title: str, call_no: str, borrowed: int
) -> Optional[sqlite3.Row]:
    """按题名/索书号查找，且 is_borrow 须等于 borrowed。"""
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
            "SELECT * FROM library_book WHERE lib_book LIKE ? AND is_borrow = ? ORDER BY id LIMIT 1",
            (f"%{title}%", borrowed),
        )
        row = cur.fetchone()
        if row:
            return row
    if call_no:
        cur.execute(
            "SELECT * FROM library_book WHERE book_key LIKE ? AND is_borrow = ? ORDER BY id LIMIT 1",
            (f"%{call_no}%", borrowed),
        )
        row = cur.fetchone()
        if row:
            return row
    return None


def lookup_circulation(title: str, call_no: str) -> str:
    """供借书确认前展示：当前在架/已借出及架位。"""
    try:
        with get_connection() as conn:
            row = find_book_row_any(conn, title, call_no)
            if not row:
                return (
                    "查询结果：演示库中暂无与所填书名或索书号匹配的记录，请核对后再确认借阅。"
                )
            st = "已借出" if int(row["is_borrow"]) == 1 else "在架可借"
            pos = row["book_pos"] or "未定"
            return (
                f"查询结果：《{row['lib_book']}》 索书号 {row['book_key']}，架位 {pos}。"
                f" 当前流通状态：{st}。"
            )
    except sqlite3.Error as e:
        logger.warning("lookup_circulation: %s", e)
        return "查询书目时数据库出错，请稍后再试。"


def borrow_book(title: str, call_no: str) -> Tuple[bool, Optional[dict], str]:
    """
    尝试借阅。
    返回 (是否办理成功, 书目快照或 None, 面向用户的说明全文)。
    成功：在架改为已借出；失败：未找到，或已借出不可再借。
    """
    try:
        with get_connection() as conn:
            row = find_book_row_any(conn, title, call_no)
            if not row:
                return (
                    False,
                    None,
                    "借阅未通过：演示库中未找到该书，请核对书名与索书号（可与确认页查询结果对照）。",
                )
            if int(row["is_borrow"]) == 1:
                pos = row["book_pos"] or "未定"
                return (
                    False,
                    _row_to_dict(row),
                    f"《{row['lib_book']}》（{row['book_key']}）当前为已借出状态，架位信息：{pos}。"
                    " 无法在演示库中重复借阅；归还后再试。",
                )
            conn.execute(
                "UPDATE library_book SET is_borrow = 1, updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            info = _row_to_dict(row)
            info["is_borrow"] = 1
            pos = row["book_pos"] or "未定"
            return (
                True,
                info,
                f"借阅已办理（演示库）：《{row['lib_book']}》 索书号 {row['book_key']}，原架位 {pos}。"
                " 系统内状态已更新为「已借出」。",
            )
    except sqlite3.Error as e:
        logger.warning("borrow_book: %s", e)
        return False, None, "借阅处理失败：数据库错误，请稍后再试。"


def return_book(title: str, call_no: str) -> Tuple[bool, Optional[dict], str]:
    """已借出则可还；在架则提示无需归还。"""
    try:
        with get_connection() as conn:
            row = find_book_row_any(conn, title, call_no)
            if not row:
                return (
                    False,
                    None,
                    "归还未通过：演示库中未找到该书，请核对书名与索书号。",
                )
            if int(row["is_borrow"]) == 0:
                pos = row["book_pos"] or "未定"
                return (
                    False,
                    _row_to_dict(row),
                    f"《{row['lib_book']}》（{row['book_key']}）当前为在架状态（{pos}），无需办理归还。",
                )
            conn.execute(
                "UPDATE library_book SET is_borrow = 0, updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
            info = _row_to_dict(row)
            info["is_borrow"] = 0
            pos = row["book_pos"] or "未定"
            return (
                True,
                info,
                f"归还已办理（演示库）：《{row['lib_book']}》 索书号 {row['book_key']}，架位 {pos}。"
                " 系统内状态已更新为「在架」。",
            )
    except sqlite3.Error as e:
        logger.warning("return_book: %s", e)
        return False, None, "归还处理失败：数据库错误，请稍后再试。"


def format_on_shelf_borrow_preview(row: dict) -> str:
    """仅根据在架查询结果行生成说明，不调全库；避免 lookup_circulation 在索书号空时误命中已借出副本。"""
    pos = (row.get("book_pos") or "").strip() or "未定"
    return (
        f"查询结果：《{row['lib_book']}》 索书号 {row['book_key']}，架位 {pos}。"
        " 当前流通状态：在架可借。"
    )


def list_on_shelf_by_title(title: str, limit: int = 50) -> List[dict]:
    """题名模糊匹配、仅在架可借（is_borrow=0）的副本列表，按索书号排序。"""
    title = (title or "").strip()
    if not title:
        return []
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT book_key, lib_book, book_pos, is_borrow
                FROM library_book
                WHERE is_borrow = 0 AND lib_book LIKE ?
                ORDER BY book_key
                LIMIT ?
                """,
                (f"%{title}%", limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        logger.warning("list_on_shelf_by_title: %s", e)
        return []


def list_borrowed_by_title(title: str, limit: int = 50) -> List[dict]:
    """题名模糊匹配、仅已借出（is_borrow=1）的副本列表，用于还书时选择。"""
    title = (title or "").strip()
    if not title:
        return []
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT book_key, lib_book, book_pos, is_borrow
                FROM library_book
                WHERE is_borrow = 1 AND lib_book LIKE ?
                ORDER BY book_key
                LIMIT ?
                """,
                (f"%{title}%", limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        logger.warning("list_borrowed_by_title: %s", e)
        return []


def get_catalog_overview(limit: int = 12) -> dict:
    """返回馆藏总览：总量、在架/已借出数量，以及部分在架书目。"""
    try:
        with get_connection() as conn:
            stat = conn.execute(
                """
                SELECT
                  COUNT(1) AS total,
                  SUM(CASE WHEN is_borrow = 0 THEN 1 ELSE 0 END) AS on_shelf,
                  SUM(CASE WHEN is_borrow = 1 THEN 1 ELSE 0 END) AS borrowed
                FROM library_book
                """
            ).fetchone()
            rows = conn.execute(
                """
                SELECT book_key, lib_book, book_pos
                FROM library_book
                WHERE is_borrow = 0
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return {
                "total": int(stat["total"] or 0),
                "on_shelf": int(stat["on_shelf"] or 0),
                "borrowed": int(stat["borrowed"] or 0),
                "rows": [_row_to_dict(r) for r in rows],
            }
    except sqlite3.Error as e:
        logger.warning("get_catalog_overview: %s", e)
        return {"total": 0, "on_shelf": 0, "borrowed": 0, "rows": []}


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
        logger.warning("recommend_on_shelf: %s", e)
        return []
