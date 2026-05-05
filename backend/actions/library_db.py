"""馆藏书目 SQLite：默认库文件在 backend/data/library.db，可用环境变量 LIBRARY_SQLITE_PATH 覆盖。"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .book_catalog_seed import generate_bulk_rows, minimum_catalog_size

logger = logging.getLogger(__name__)
MAX_ACTIVE_BORROW = 3

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

CREATE TABLE IF NOT EXISTS borrow_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER,
    book_key TEXT NOT NULL,
    lib_book TEXT NOT NULL,
    borrower_id TEXT NOT NULL,
    borrower_name TEXT NOT NULL,
    borrow_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    returned_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_borrow_record_book_key ON borrow_record (book_key);
CREATE INDEX IF NOT EXISTS idx_borrow_record_borrower_id ON borrow_record (borrower_id);
CREATE INDEX IF NOT EXISTS idx_borrow_record_created_at ON borrow_record (created_at);
"""

# 少量经典演示行（与早期种子一致）；其余由 book_catalog_seed 补至 MIN 条
_SEED_ROWS: List[Tuple[str, str, str, int]] = [
    ("B-HLM-001", "红楼梦（人民文学）", "文学库 A-01", 1),
    ("B-XYJ-002", "西游记（人民文学）", "文学库 A-02", 0),
    ("TP311.5/PY-01", "Python 程序设计", "科技库 T-03", 0),
    ("TP311/DL-01", "深度学习入门", "科技库 T-05", 0),
    ("I247.5/XX-01", "平凡的世界", "文学库 B-10", 0),
    ("I313/CCK-01", "川端康成：雪国（节选导读）", "文学库 J-03", 0),
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
    _ensure_borrow_record_columns(conn)
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


def _ensure_borrow_record_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(borrow_record)")
    cols = {str(r["name"]) for r in cur.fetchall()}
    if cols and "returned_at" not in cols:
        conn.execute("ALTER TABLE borrow_record ADD COLUMN returned_at TEXT")
        conn.commit()


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


def get_active_borrow_count(borrower_id: str) -> int:
    borrower_id = (borrower_id or "").strip()
    if not borrower_id:
        return 0
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM borrow_record
                WHERE borrower_id = ? AND returned_at IS NULL
                """,
                (borrower_id,),
            ).fetchone()
            return int((row["c"] if row else 0) or 0)
    except sqlite3.Error as e:
        logger.warning("get_active_borrow_count: %s", e)
        return 0


def borrow_book(title: str, call_no: str, borrower_id: str = "") -> Tuple[bool, Optional[dict], str]:
    """
    尝试借阅。
    返回 (是否办理成功, 书目快照或 None, 面向用户的说明全文)。
    成功：在架改为已借出；失败：未找到，或已借出不可再借。
    """
    try:
        with get_connection() as conn:
            normalized_borrower = (borrower_id or "").strip()
            if normalized_borrower:
                row_count = conn.execute(
                    """
                    SELECT COUNT(1) AS c
                    FROM borrow_record
                    WHERE borrower_id = ? AND returned_at IS NULL
                    """,
                    (normalized_borrower,),
                ).fetchone()
                active_count = int((row_count["c"] if row_count else 0) or 0)
                if active_count >= MAX_ACTIVE_BORROW:
                    return (
                        False,
                        None,
                        f"借阅未通过：当前账号未归还 {active_count} 本，已达到上限 {MAX_ACTIVE_BORROW} 本。"
                        "请先归还至少 1 本后再借阅。",
                    )
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


def return_book(title: str, call_no: str, borrower_id: str = "") -> Tuple[bool, Optional[dict], str]:
    """已借出则可还；在架则提示无需归还。若提供 borrower_id，则仅允许归还该账号名下待还记录。"""
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
            normalized_borrower = (borrower_id or "").strip()
            if normalized_borrower:
                own_active = conn.execute(
                    """
                    SELECT id
                    FROM borrow_record
                    WHERE borrower_id = ? AND book_key = ? AND returned_at IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (normalized_borrower, row["book_key"]),
                ).fetchone()
                if not own_active:
                    return (
                        False,
                        _row_to_dict(row),
                        "归还未通过：当前账号下无此书的待还记录，请核对后重试。",
                    )
            conn.execute(
                "UPDATE library_book SET is_borrow = 0, updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            if normalized_borrower:
                conn.execute(
                    """
                    UPDATE borrow_record
                    SET returned_at = datetime('now')
                    WHERE id = (
                        SELECT id
                        FROM borrow_record
                        WHERE borrower_id = ? AND book_key = ? AND returned_at IS NULL
                        ORDER BY id DESC
                        LIMIT 1
                    )
                    """,
                    (normalized_borrower, row["book_key"]),
                )
            else:
                conn.execute(
                    """
                    UPDATE borrow_record
                    SET returned_at = datetime('now')
                    WHERE id = (
                        SELECT id
                        FROM borrow_record
                        WHERE book_key = ? AND returned_at IS NULL
                        ORDER BY id DESC
                        LIMIT 1
                    )
                    """,
                    (row["book_key"],),
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


def list_active_borrow_records(borrower_id: str, limit: int = 100) -> List[dict]:
    """按账号查询未归还记录，用于前端可视化还书列表。"""
    borrower_id = (borrower_id or "").strip()
    if not borrower_id:
        return []
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT r.book_key, r.lib_book, r.borrower_id, r.borrower_name, r.borrow_at, r.due_at, b.book_pos
                FROM borrow_record r
                LEFT JOIN library_book b ON b.book_key = r.book_key
                WHERE r.borrower_id = ? AND r.returned_at IS NULL
                ORDER BY r.id DESC
                LIMIT ?
                """,
                (borrower_id, limit),
            )
            rows = []
            for r in cur.fetchall():
                rows.append(
                    {
                        "book_key": str(r["book_key"] or "").strip(),
                        "lib_book": str(r["lib_book"] or "").strip(),
                        "borrower_id": str(r["borrower_id"] or "").strip(),
                        "borrower_name": str(r["borrower_name"] or "").strip(),
                        "borrow_at": str(r["borrow_at"] or "").strip(),
                        "due_at": str(r["due_at"] or "").strip(),
                        "book_pos": str(r["book_pos"] or "").strip(),
                    }
                )
            return rows
    except sqlite3.Error as e:
        logger.warning("list_active_borrow_records: %s", e)
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


# 阅读推荐：主题 → 检索词（越靠前越优先匹配题名）
_TOPIC_SEARCH_EXPANSIONS: Dict[str, List[str]] = {
    "日本文学": [
        "日本文学",
        "日本",
        "川端",
        "夏目",
        "村上",
        "太宰",
        "芥川",
        "东野",
        "江户川",
        "松本清张",
        "推理小说",
    ],
    "英国文学": ["英国文学", "英国", "莎士比亚", "狄更斯", "简·奥斯汀", "勃朗特"],
    "美国文学": ["美国文学", "美国", "海明威", "马克·吐温", "福克纳"],
    "法国文学": ["法国文学", "法国", "雨果", "巴尔扎克", "加缪"],
    "俄国文学": ["俄国文学", "俄罗斯文学", "俄国", "俄罗斯", "托尔斯泰", "陀思妥耶夫斯基", "契诃夫", "普希金"],
    "科幻": ["科幻", "银河帝国", "基地", "三体", "火星"],
    "推理": ["推理", "悬疑", "侦探"],
    "诗歌": ["诗歌", "诗集", "诗词"],
}


def expand_topic_search_terms(topic: str) -> List[str]:
    """按用户主题展开 SQLite LIKE 检索词；保留顺序并去重。"""
    t = (topic or "").strip()
    if not t:
        return []
    keys = sorted(_TOPIC_SEARCH_EXPANSIONS.keys(), key=len, reverse=True)
    for key in keys:
        if key in t or (len(t) <= len(key) + 2 and t in key):
            head = key if key in t else t
            rest = [x for x in _TOPIC_SEARCH_EXPANSIONS[key] if x != head]
            terms = [head] + rest
            seen: set[str] = set()
            out: List[str] = []
            for x in terms:
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out
    return [t]


def _rank_rows_for_reading_topic(rows: List[dict], terms: List[str], raw_topic: str) -> List[dict]:
    """按检索词命中优先级排序；在架优先于已借出；弱化明显跑题条目。"""

    def score_row(r: dict) -> Tuple[int, int, str]:
        title = str(r.get("lib_book") or "")
        best = 999
        for i, term in enumerate(terms):
            if term and term in title:
                best = min(best, i)
        if best == 999:
            best = 1000
        # 用户要日本相关时，不含「日本」的中国古典/明确中国文学倾向的条目降权
        if "日本" in raw_topic:
            if "日本" not in title and any(
                k in title for k in ("红楼梦", "西游记", "水浒传", "三国演义", "中国文学史")
            ):
                best += 120
            if "日本" not in title and "中国" in title and "外国" not in title and "世界" not in title:
                best += 40
        borrow = int(r.get("is_borrow") or 0)
        return (best, borrow, title)

    return sorted(rows, key=score_row)


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


def catalog_search_by_topic(topic: Optional[str], limit: int = 50) -> List[dict]:
    """
    按题名模糊匹配馆藏（含在架与已借出），供阅读推荐与 LLM 事实上下文。
    支持主题词扩展与相关性排序；在架优先于已借出。
    """
    topic = (topic or "").strip()
    if not topic:
        return []
    terms = expand_topic_search_terms(topic)
    if not terms:
        terms = [topic]
    try:
        with get_connection() as conn:
            placeholders = " OR ".join(["lib_book LIKE ?" for _ in terms])
            like_params = [f"%{t}%" for t in terms]
            fetch_cap = min(400, max(int(limit) * 8, 80))
            cur = conn.execute(
                f"""
                SELECT book_key, lib_book, book_pos, is_borrow
                FROM library_book
                WHERE {placeholders}
                LIMIT ?
                """,
                (*like_params, fetch_cap),
            )
            raw_rows = [_row_to_dict(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        logger.warning("catalog_search_by_topic: %s", e)
        return []

    by_key: Dict[str, dict] = {}
    for r in raw_rows:
        k = str(r.get("book_key") or "")
        if k and k not in by_key:
            by_key[k] = r
    ranked = _rank_rows_for_reading_topic(list(by_key.values()), terms, topic)
    return ranked[: int(limit)]


def list_catalog_books(limit: int = 500) -> List[dict]:
    """返回馆藏书目列表（含在架/已借出状态），用于前端借书交互表单。"""
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT book_key, lib_book, book_pos, is_borrow
                FROM library_book
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        logger.warning("list_catalog_books: %s", e)
        return []


def record_borrow_transaction(
    book_snapshot: Optional[dict],
    borrower_id: str,
    borrower_name: str,
    borrow_at: str,
    due_at: str,
) -> bool:
    """写入借阅登记记录（仅在借阅成功后调用）。"""
    if not book_snapshot:
        return False
    borrower_id = (borrower_id or "").strip()
    borrower_name = (borrower_name or "").strip()
    borrow_at = (borrow_at or "").strip()
    due_at = (due_at or "").strip()
    if not (borrower_id and borrower_name and borrow_at and due_at):
        return False
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO borrow_record (
                    book_id, book_key, lib_book, borrower_id, borrower_name, borrow_at, due_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_snapshot.get("id"),
                    str(book_snapshot.get("book_key") or "").strip(),
                    str(book_snapshot.get("lib_book") or "").strip(),
                    borrower_id,
                    borrower_name,
                    borrow_at,
                    due_at,
                ),
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.warning("record_borrow_transaction: %s", e)
        return False


def list_borrow_records(borrower_id: str, limit: int = 20) -> List[dict]:
    borrower_id = (borrower_id or "").strip()
    if not borrower_id:
        return []
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                SELECT book_key, lib_book, borrower_id, borrower_name, borrow_at, due_at, returned_at, created_at
                FROM borrow_record
                WHERE borrower_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (borrower_id, limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        logger.warning("list_borrow_records: %s", e)
        return []
