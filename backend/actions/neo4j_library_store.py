"""馆藏书目与流通：Neo4j（:LibraryBook 以 book_key 唯一标识；:BorrowRecord）。书目元数据均为 LibraryBook 节点属性。

目录条数「撑满」行为由 ``book_catalog_seed.minimum_catalog_size`` 与环境变量 ``LIB_AGENT_MIN_CATALOG`` 控制（默认不批量补孤立 SEED）。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

try:
    from kg_module.env_bootstrap import load_repo_dotenv

    load_repo_dotenv()
except Exception:
    pass

from kg_module.neo4j_auth import driver_kwargs, neo4j_use_graph, resolve_auth

from .book_catalog_seed import generate_bulk_rows, minimum_catalog_size

logger = logging.getLogger(__name__)
MAX_ACTIVE_BORROW = 3

DEFAULT_URI = "bolt://localhost:7687"

_SEED_ROWS: List[Tuple[str, str, str, int, str]] = [
    (
        "B-HLM-001",
        "红楼梦（人民文学）",
        "文学库 A-01",
        1,
        "中国古典小说巅峰之作，以贾府兴衰写尽人情与世态。",
    ),
    (
        "B-XYJ-002",
        "西游记（人民文学）",
        "文学库 A-02",
        0,
        "神魔小说经典，唐僧师徒西天取经的历险长卷。",
    ),
    (
        "TP311.5/PY-01",
        "Python 程序设计",
        "科技库 T-03",
        0,
        "面向初学者的编程入门与项目实践。",
    ),
    (
        "TP311/DL-01",
        "深度学习入门",
        "科技库 T-05",
        0,
        "神经网络与表示学习的基础概念与实现导引。",
    ),
    (
        "I247.5/XX-01",
        "平凡的世界",
        "文学库 B-10",
        0,
        "路遥现实主义长篇，陕北城乡变革中的青年命运。",
    ),
    (
        "I313/CCK-01",
        "川端康成：雪国（节选导读）",
        "文学库 J-03",
        0,
        "诺奖作家代表作节选与导读，徒劳之美与物哀传统。",
    ),
]

_BOOT_LOCK = threading.Lock()
_BOOT_DONE = False

_CONSTRAINTS = [
    "CREATE CONSTRAINT library_book_key IF NOT EXISTS "
    "FOR (lb:LibraryBook) REQUIRE lb.book_key IS UNIQUE",
]

# 占位流水：在首次真实借阅前让图中存在 :BorrowRecord 及全套属性键，避免 Neo4j 5+ 对「空标签/未出现过的属性」刷屏告警；已归还，不计入在借。
_BORROW_RECORD_BOOTSTRAP_BOOK_KEY = "__LIB_AGENT_BOOTSTRAP__"

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


def _graph_unavailable_message() -> str:
    return (
        "书目服务未就绪：请配置 Neo4j（NEO4J_PASSWORD 或 NEO4J_AUTH_NONE=1）并确保数据库可连。"
    )


def _open_driver():
    try:
        from kg_module.env_bootstrap import load_repo_dotenv

        load_repo_dotenv()
    except Exception:
        pass
    if not neo4j_use_graph():
        logger.warning(
            "neo4j_library_store：未启用 Neo4j（需环境变量 NEO4J_PASSWORD 或 NEO4J_AUTH_NONE=1）。"
            "请确认 Action 启动前已配置仓库根目录或 backend 下的 .env，并已重启 Action。"
        )
        return None
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return None
    try:
        auth = resolve_auth()
    except ValueError:
        return None
    uri = (os.environ.get("NEO4J_URI") or DEFAULT_URI).strip()
    return GraphDatabase.driver(uri, auth=auth, **driver_kwargs())


_LIBRARY_BOOK_CONSTRAINT_NAME = "library_book_key"


def _ensure_library_book_constraint(session) -> None:
    """仅在缺失时创建 LibraryBook 唯一约束，避免 Neo4j 对 IF NOT EXISTS 仍返回 SCHEMA INFORMATION 通知刷屏。"""
    try:
        row = session.run(
            "SHOW CONSTRAINTS WHERE name = $n RETURN name LIMIT 1",
            n=_LIBRARY_BOOK_CONSTRAINT_NAME,
        ).single()
        if row:
            return
    except Exception as exc:  # pragma: no cover - 极旧实例无 SHOW 时回退
        logger.debug("neo4j_library_store SHOW CONSTRAINTS: %s", exc)
    q = _CONSTRAINTS[0]
    try:
        session.run(q)
    except Exception as exc:  # pragma: no cover
        logger.warning("neo4j_library_store constraint: %s", exc)


def _ensure_bootstrap_with_session(session) -> None:
    global _BOOT_DONE
    if not _BOOT_DONE:
        with _BOOT_LOCK:
            if not _BOOT_DONE:
                _ensure_library_book_constraint(session)
                n = int(session.run("MATCH (lb:LibraryBook) RETURN count(lb) AS c").single()["c"] or 0)
                if n == 0:
                    for book_key, lib_book, book_pos, is_borrow, summary in _SEED_ROWS:
                        session.run(
                            """
                            MERGE (lb:LibraryBook {book_key: $bk})
                            ON CREATE SET
                              lb.lib_book = $t,
                              lb.book_pos = $p,
                              lb.is_borrow = $ib,
                              lb.summary = $sm
                            """,
                            bk=book_key,
                            t=lib_book,
                            p=book_pos or "",
                            ib=int(is_borrow),
                            sm=summary or "",
                        )
                n = int(session.run("MATCH (lb:LibraryBook) RETURN count(lb) AS c").single()["c"] or 0)
                min_n = minimum_catalog_size()
                if n < min_n:
                    need = min_n - n
                    bulk = generate_bulk_rows(need, key_offset=n)
                    for book_key, lib_book, book_pos, is_borrow, summary in bulk:
                        session.run(
                            """
                            MERGE (lb:LibraryBook {book_key: $bk})
                            ON CREATE SET
                              lb.lib_book = $t,
                              lb.book_pos = $p,
                              lb.is_borrow = $ib,
                              lb.summary = $sm
                            """,
                            bk=book_key,
                            t=lib_book,
                            p=book_pos or "",
                            ib=int(is_borrow),
                            sm=summary or "",
                        )
                    logger.info("Seeded Neo4j LibraryBook rows toward >= %s (added %s).", min_n, need)
                session.run(
                    """
                    MERGE (br:BorrowRecord {book_key: $bk})
                    ON CREATE SET
                      br.borrower_id = '__bootstrap__',
                      br.borrower_name = '',
                      br.lib_book = '',
                      br.borrow_at = '',
                      br.due_at = '',
                      br.returned_at = datetime(),
                      br.created_at = datetime()
                    """,
                    bk=_BORROW_RECORD_BOOTSTRAP_BOOK_KEY,
                )
                _BOOT_DONE = True
    _cleanup_legacy_shelf_graph(session)
    _backfill_empty_library_summaries(session)


def _cleanup_legacy_shelf_graph(session) -> None:
    """移除历史版本中的架位节点与 LOCATED_AT；馆藏架位仅以 LibraryBook.book_pos 属性表示。"""
    try:
        session.run("MATCH ()-[r:LOCATED_AT]->() DELETE r")
        session.run("MATCH (sl:ShelfLocation) DETACH DELETE sl")
        session.run("DROP CONSTRAINT shelf_location_pos_key IF EXISTS")
    except Exception as exc:  # pragma: no cover
        logger.debug("neo4j_library_store legacy shelf cleanup: %s", exc)


def _backfill_empty_library_summaries(session) -> None:
    """旧数据无 summary 时写入占位简介，便于列表与检索。"""
    try:
        session.run(
            """
            MATCH (lb:LibraryBook)
            WHERE lb.summary IS NULL OR trim(coalesce(lb.summary, '')) = ''
            SET lb.summary = '演示馆藏教参副本，借阅状态见 is_borrow；架位见 book_pos。'
            """
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("neo4j_library_store summary backfill: %s", exc)


def ensure_bootstrap() -> bool:
    """连接并执行约束与种子（幂等）。"""
    drv = _open_driver()
    if drv is None:
        return False
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
        return True
    finally:
        drv.close()


def _library_book_as_dict(node: Any) -> dict:
    d = dict(node)
    eid = getattr(node, "element_id", None)
    d["id"] = eid if eid is not None else d.get("book_key")
    d.setdefault("lib_book", d.get("lib_book") or "")
    d.setdefault("book_key", d.get("book_key") or "")
    d.setdefault("book_pos", d.get("book_pos") or "")
    d.setdefault("summary", d.get("summary") or "")
    d["is_borrow"] = int(d.get("is_borrow") or 0)
    return d


def _tx_find_book_any(tx, title: str, call_no: str) -> Optional[Any]:
    title = (title or "").strip()
    call_no = (call_no or "").strip()
    if call_no:
        r = tx.run(
            "MATCH (lb:LibraryBook {book_key: $ck}) RETURN lb LIMIT 1",
            ck=call_no,
        ).single()
        if r:
            return r["lb"]
        r = tx.run(
            """
            MATCH (lb:LibraryBook)
            WHERE lb.book_key CONTAINS $ck
            RETURN lb ORDER BY lb.book_key LIMIT 1
            """,
            ck=call_no,
        ).single()
        if r:
            return r["lb"]
    if title:
        r = tx.run(
            """
            MATCH (lb:LibraryBook)
            WHERE lb.lib_book CONTAINS $tl
            RETURN lb ORDER BY lb.book_key LIMIT 1
            """,
            tl=title,
        ).single()
        if r:
            return r["lb"]
    if call_no:
        # 再次尝试仅题名路径已穷尽；call_no fuzzy 上文已覆盖
        pass
    return None


def lookup_circulation(title: str, call_no: str) -> str:
    drv = _open_driver()
    if drv is None:
        return _graph_unavailable_message()
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)

            def _read(tx):
                lb = _tx_find_book_any(tx, title, call_no)
                return lb

            lb = session.execute_read(_read)
            if not lb:
                return (
                    "查询结果：演示库中暂无与所填书名或索书号匹配的记录，请核对后再确认借阅。"
                )
            d = _library_book_as_dict(lb)
            st = "已借出" if int(d["is_borrow"]) == 1 else "在架可借"
            pos = (d.get("book_pos") or "").strip() or "未定"
            sm = (d.get("summary") or "").strip()
            tail = f" 简介摘录：{sm[:160]}…" if len(sm) > 160 else (f" 简介：{sm}" if sm else "")
            return (
                f"查询结果：《{d['lib_book']}》 索书号 {d['book_key']}，架位 {pos}。"
                f" 当前流通状态：{st}。{tail}"
            )
    except Exception as exc:  # pragma: no cover
        logger.warning("lookup_circulation: %s", exc)
        return "查询书目时数据库出错，请稍后再试。"
    finally:
        drv.close()


def get_active_borrow_count(borrower_id: str) -> int:
    borrower_id = (borrower_id or "").strip()
    if not borrower_id:
        return 0
    drv = _open_driver()
    if drv is None:
        return 0
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            row = session.run(
                """
                MATCH (br:BorrowRecord {borrower_id: $bid})
                WHERE br.returned_at IS NULL
                RETURN count(br) AS c
                """,
                bid=borrower_id,
            ).single()
            return int((row["c"] if row else 0) or 0)
    except Exception as exc:
        logger.warning("get_active_borrow_count: %s", exc)
        return 0
    finally:
        drv.close()


def borrow_book(title: str, call_no: str, borrower_id: str = "") -> Tuple[bool, Optional[dict], str]:
    drv = _open_driver()
    if drv is None:
        return False, None, f"借阅未通过：{_graph_unavailable_message()}"

    result: Dict[str, Any] = {}

    def work(tx):
        normalized_borrower = (borrower_id or "").strip()
        if normalized_borrower:
            row_count = tx.run(
                """
                MATCH (br:BorrowRecord {borrower_id: $bid})
                WHERE br.returned_at IS NULL
                RETURN count(br) AS c
                """,
                bid=normalized_borrower,
            ).single()
            active_count = int((row_count["c"] if row_count else 0) or 0)
            if active_count >= MAX_ACTIVE_BORROW:
                result["out"] = (
                    False,
                    None,
                    f"借阅未通过：当前账号未归还 {active_count} 本，已达到上限 {MAX_ACTIVE_BORROW} 本。"
                    "请先归还至少 1 本后再借阅。",
                )
                return
        row = _tx_find_book_any(tx, title, call_no)
        if not row:
            result["out"] = (
                False,
                None,
                "借阅未通过：演示库中未找到该书，请核对书名与索书号（可与确认页查询结果对照）。",
            )
            return
        d = _library_book_as_dict(row)
        if int(d["is_borrow"]) == 1:
            pos = (d.get("book_pos") or "").strip() or "未定"
            result["out"] = (
                False,
                d,
                f"《{d['lib_book']}》（{d['book_key']}）当前为已借出状态，架位信息：{pos}。"
                " 无法在演示库中重复借阅；归还后再试。",
            )
            return
        tx.run(
            """
            MATCH (lb:LibraryBook {book_key: $bk})
            SET lb.is_borrow = 1
            """,
            bk=d["book_key"],
        )
        d2 = dict(d)
        d2["is_borrow"] = 1
        pos = (d.get("book_pos") or "").strip() or "未定"
        result["out"] = (
            True,
            d2,
            f"借阅已办理（演示库）：《{d['lib_book']}》 索书号 {d['book_key']}，原架位 {pos}。"
            " 系统内状态已更新为「已借出」。",
        )

    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            session.execute_write(work)
        return result.get("out", (False, None, "借阅处理失败，请稍后再试。"))
    except Exception as exc:
        logger.warning("borrow_book: %s", exc)
        return False, None, "借阅处理失败：数据库错误，请稍后再试。"
    finally:
        drv.close()


def return_book(title: str, call_no: str, borrower_id: str = "") -> Tuple[bool, Optional[dict], str]:
    drv = _open_driver()
    if drv is None:
        return False, None, f"归还未通过：{_graph_unavailable_message()}"

    result: Dict[str, Any] = {}

    def work(tx):
        row = _tx_find_book_any(tx, title, call_no)
        if not row:
            result["out"] = (
                False,
                None,
                "归还未通过：演示库中未找到该书，请核对书名与索书号。",
            )
            return
        d = _library_book_as_dict(row)
        if int(d["is_borrow"]) == 0:
            pos = (d.get("book_pos") or "").strip() or "未定"
            result["out"] = (
                False,
                d,
                f"《{d['lib_book']}》（{d['book_key']}）当前为在架状态（{pos}），无需办理归还。",
            )
            return
        normalized_borrower = (borrower_id or "").strip()
        if normalized_borrower:
            own = tx.run(
                """
                MATCH (br:BorrowRecord)
                WHERE br.borrower_id = $bid AND br.book_key = $bk AND br.returned_at IS NULL
                RETURN br ORDER BY br.created_at DESC LIMIT 1
                """,
                bid=normalized_borrower,
                bk=d["book_key"],
            ).single()
            if not own:
                result["out"] = (
                    False,
                    d,
                    "归还未通过：当前账号下无此书的待还记录，请核对后重试。",
                )
                return
        tx.run(
            """
            MATCH (lb:LibraryBook {book_key: $bk})
            SET lb.is_borrow = 0
            """,
            bk=d["book_key"],
        )
        if normalized_borrower:
            tx.run(
                """
                MATCH (br:BorrowRecord)
                WHERE br.borrower_id = $bid AND br.book_key = $bk AND br.returned_at IS NULL
                WITH br ORDER BY br.created_at DESC LIMIT 1
                SET br.returned_at = datetime()
                """,
                bid=normalized_borrower,
                bk=d["book_key"],
            )
        else:
            tx.run(
                """
                MATCH (br:BorrowRecord {book_key: $bk})
                WHERE br.returned_at IS NULL
                WITH br ORDER BY br.created_at DESC LIMIT 1
                SET br.returned_at = datetime()
                """,
                bk=d["book_key"],
            )
        d2 = dict(d)
        d2["is_borrow"] = 0
        pos = (d.get("book_pos") or "").strip() or "未定"
        result["out"] = (
            True,
            d2,
            f"归还已办理（演示库）：《{d['lib_book']}》 索书号 {d['book_key']}，架位 {pos}。"
            " 系统内状态已更新为「在架」。",
        )

    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            session.execute_write(work)
        return result.get("out", (False, None, "归还处理失败，请稍后再试。"))
    except Exception as exc:
        logger.warning("return_book: %s", exc)
        return False, None, "归还处理失败：数据库错误，请稍后再试。"
    finally:
        drv.close()


def format_on_shelf_borrow_preview(row: dict) -> str:
    pos = (row.get("book_pos") or "").strip() or "未定"
    sm = (row.get("summary") or "").strip()
    tail = f" {sm[:120]}…" if len(sm) > 120 else (f" {sm}" if sm else "")
    return (
        f"查询结果：《{row['lib_book']}》 索书号 {row['book_key']}，架位 {pos}。"
        f" 当前流通状态：在架可借。{tail}"
    )


def list_on_shelf_by_title(title: str, limit: int = 50) -> List[dict]:
    title = (title or "").strip()
    if not title:
        return []
    drv = _open_driver()
    if drv is None:
        return []
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            recs = session.run(
                """
                MATCH (lb:LibraryBook)
                WHERE lb.is_borrow = 0 AND lb.lib_book CONTAINS $t
                RETURN lb.book_key AS book_key,
                       lb.lib_book AS lib_book,
                       lb.book_pos AS book_pos,
                       coalesce(lb.summary, '') AS summary,
                       lb.is_borrow AS is_borrow
                ORDER BY lb.book_key
                LIMIT $lim
                """,
                t=title,
                lim=int(limit),
            )
            return [dict(r) for r in recs]
    except Exception as exc:
        logger.warning("list_on_shelf_by_title: %s", exc)
        return []
    finally:
        drv.close()


def list_borrowed_by_title(title: str, limit: int = 50) -> List[dict]:
    title = (title or "").strip()
    if not title:
        return []
    drv = _open_driver()
    if drv is None:
        return []
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            recs = session.run(
                """
                MATCH (lb:LibraryBook)
                WHERE lb.is_borrow = 1 AND lb.lib_book CONTAINS $t
                RETURN lb.book_key AS book_key,
                       lb.lib_book AS lib_book,
                       lb.book_pos AS book_pos,
                       coalesce(lb.summary, '') AS summary,
                       lb.is_borrow AS is_borrow
                ORDER BY lb.book_key
                LIMIT $lim
                """,
                t=title,
                lim=int(limit),
            )
            return [dict(r) for r in recs]
    except Exception as exc:
        logger.warning("list_borrowed_by_title: %s", exc)
        return []
    finally:
        drv.close()


def get_library_book_by_call_number(book_key: str) -> Optional[dict]:
    """按索书号精确取一条 LibraryBook（用于介绍等）。"""
    bk = (book_key or "").strip().upper()
    if not bk:
        return None
    drv = _open_driver()
    if drv is None:
        return None
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            row = session.run(
                """
                MATCH (lb:LibraryBook {book_key: $bk})
                RETURN lb.book_key AS book_key,
                       lb.lib_book AS lib_book,
                       lb.book_pos AS book_pos,
                       coalesce(lb.summary, '') AS summary,
                       lb.is_borrow AS is_borrow
                LIMIT 1
                """,
                bk=bk,
            ).single()
            if not row:
                return None
            return dict(row)
    except Exception as exc:
        logger.warning("get_library_book_by_call_number: %s", exc)
        return None
    finally:
        drv.close()


def search_library_books_for_intro(title: str, limit: int = 8) -> List[dict]:
    """按题名关键词检索馆藏副本（在架/已借均可），精确题名优先。"""
    title = (title or "").strip()
    if not title:
        return []
    drv = _open_driver()
    if drv is None:
        return []
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            recs = session.run(
                """
                MATCH (lb:LibraryBook)
                WHERE toLower(lb.lib_book) CONTAINS toLower($t)
                RETURN lb.book_key AS book_key,
                       lb.lib_book AS lib_book,
                       lb.book_pos AS book_pos,
                       coalesce(lb.summary, '') AS summary,
                       lb.is_borrow AS is_borrow
                ORDER BY
                  CASE WHEN toLower(lb.lib_book) = toLower($exact) THEN 0 ELSE 1 END,
                  size(toString(lb.lib_book)),
                  lb.book_key
                LIMIT $lim
                """,
                t=title,
                exact=title,
                lim=int(limit),
            )
            return [dict(r) for r in recs]
    except Exception as exc:
        logger.warning("search_library_books_for_intro: %s", exc)
        return []
    finally:
        drv.close()


def list_active_borrow_records(borrower_id: str, limit: int = 100) -> List[dict]:
    borrower_id = (borrower_id or "").strip()
    if not borrower_id:
        return []
    drv = _open_driver()
    if drv is None:
        return []
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            recs = session.run(
                """
                MATCH (br:BorrowRecord {borrower_id: $bid})
                WHERE br.returned_at IS NULL
                OPTIONAL MATCH (lb:LibraryBook {book_key: br.book_key})
                RETURN br.book_key AS book_key,
                       br.lib_book AS lib_book,
                       br.borrower_id AS borrower_id,
                       br.borrower_name AS borrower_name,
                       br.borrow_at AS borrow_at,
                       br.due_at AS due_at,
                       coalesce(lb.book_pos, '') AS book_pos,
                       coalesce(lb.summary, '') AS summary
                LIMIT $lim
                """,
                bid=borrower_id,
                lim=int(limit),
            )
            out = []
            for r in recs:
                out.append(
                    {
                        "book_key": str(r["book_key"] or "").strip(),
                        "lib_book": str(r["lib_book"] or "").strip(),
                        "borrower_id": str(r["borrower_id"] or "").strip(),
                        "borrower_name": str(r["borrower_name"] or "").strip(),
                        "borrow_at": str(r["borrow_at"] or "").strip(),
                        "due_at": str(r["due_at"] or "").strip(),
                        "book_pos": str(r["book_pos"] or "").strip(),
                        "summary": str(r["summary"] or "").strip(),
                    }
                )
            return out
    except Exception as exc:
        logger.warning("list_active_borrow_records: %s", exc)
        return []
    finally:
        drv.close()


def get_library_collection_stats() -> Dict[str, int]:
    """馆藏计数（一次聚合查询，供总览与分页接口）。"""
    drv = _open_driver()
    if drv is None:
        return {"total": 0, "on_shelf": 0, "borrowed": 0}
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            stat = session.run(
                """
                MATCH (lb:LibraryBook)
                RETURN count(lb) AS total,
                       sum(CASE WHEN lb.is_borrow = 0 THEN 1 ELSE 0 END) AS on_shelf,
                       sum(CASE WHEN lb.is_borrow = 1 THEN 1 ELSE 0 END) AS borrowed
                """
            ).single()
            return {
                "total": int(stat["total"] or 0),
                "on_shelf": int(stat["on_shelf"] or 0),
                "borrowed": int(stat["borrowed"] or 0),
            }
    except Exception as exc:
        logger.warning("get_library_collection_stats: %s", exc)
        return {"total": 0, "on_shelf": 0, "borrowed": 0}
    finally:
        drv.close()


def list_on_shelf_overview_page(page: int, page_size: int) -> List[Dict[str, Any]]:
    """在架书目一页（按 book_key 排序）；page 从 1 起。"""
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    skip = (page - 1) * page_size
    drv = _open_driver()
    if drv is None:
        return []
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            rows = session.run(
                """
                MATCH (lb:LibraryBook)
                WHERE lb.is_borrow = 0
                RETURN lb.book_key AS book_key,
                       lb.lib_book AS lib_book,
                       lb.book_pos AS book_pos,
                       coalesce(lb.summary, '') AS summary
                ORDER BY lb.book_key
                SKIP $skip
                LIMIT $lim
                """,
                skip=int(skip),
                lim=int(page_size),
            )
            return [
                {
                    "book_key": str(r["book_key"] or "").strip(),
                    "lib_book": str(r["lib_book"] or "").strip(),
                    "book_pos": str(r["book_pos"] or "").strip(),
                    "summary": str(r.get("summary") or ""),
                }
                for r in rows
            ]
    except Exception as exc:
        logger.warning("list_on_shelf_overview_page: %s", exc)
        return []
    finally:
        drv.close()


def get_catalog_overview(limit: int = 12) -> dict:
    """兼容旧接口：统计 + 在架首页若干条。"""
    stats = get_library_collection_stats()
    raw = list_on_shelf_overview_page(1, int(limit))
    rlist = [
        {
            "book_key": r["book_key"],
            "lib_book": r["lib_book"],
            "book_pos": r["book_pos"],
            "summary": r.get("summary") or "",
        }
        for r in raw
    ]
    return {
        "total": stats["total"],
        "on_shelf": stats["on_shelf"],
        "borrowed": stats["borrowed"],
        "rows": rlist,
    }


def expand_topic_search_terms(topic: str) -> List[str]:
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
    def score_row(r: dict) -> Tuple[int, int, str]:
        title = str(r.get("lib_book") or "")
        best = 999
        for i, term in enumerate(terms):
            if term and term in title:
                best = min(best, i)
        if best == 999:
            best = 1000
        if "日本" in raw_topic:
            if "日本" not in title and any(
                k in title for k in ("红楼梦", "西游记", "水浒传", "三国演义", "中国文学史")
            ):
                best += 120
            if (
                "日本" not in title
                and "中国" in title
                and "外国" not in title
                and "世界" not in title
            ):
                best += 40
        borrow = int(r.get("is_borrow") or 0)
        return (best, borrow, title)

    return sorted(rows, key=score_row)


def catalog_search_by_topic(topic: Optional[str], limit: int = 50) -> List[dict]:
    topic = (topic or "").strip()
    if not topic:
        return []
    terms = expand_topic_search_terms(topic)
    if not terms:
        terms = [topic]
    drv = _open_driver()
    if drv is None:
        return []
    fetch_cap = min(400, max(int(limit) * 8, 80))
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            recs = session.run(
                """
                MATCH (lb:LibraryBook)
                WHERE ANY(term IN $terms WHERE lb.lib_book CONTAINS term
                     OR coalesce(lb.summary, '') CONTAINS term)
                RETURN lb.book_key AS book_key,
                       lb.lib_book AS lib_book,
                       lb.book_pos AS book_pos,
                       coalesce(lb.summary, '') AS summary,
                       lb.is_borrow AS is_borrow
                LIMIT $cap
                """,
                terms=terms,
                cap=int(fetch_cap),
            )
            raw_rows = [dict(r) for r in recs]
    except Exception as exc:
        logger.warning("catalog_search_by_topic: %s", exc)
        return []
    finally:
        drv.close()

    by_key: Dict[str, dict] = {}
    for r in raw_rows:
        k = str(r.get("book_key") or "")
        if k and k not in by_key:
            by_key[k] = r
    ranked = _rank_rows_for_reading_topic(list(by_key.values()), terms, topic)
    return ranked[: int(limit)]


def list_catalog_books(limit: int = 500) -> List[dict]:
    drv = _open_driver()
    if drv is None:
        return []
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            recs = session.run(
                """
                MATCH (lb:LibraryBook)
                RETURN lb.book_key AS book_key,
                       lb.lib_book AS lib_book,
                       lb.book_pos AS book_pos,
                       coalesce(lb.summary, '') AS summary,
                       lb.is_borrow AS is_borrow
                ORDER BY lb.book_key
                LIMIT $lim
                """,
                lim=int(limit),
            )
            return [dict(r) for r in recs]
    except Exception as exc:
        logger.warning("list_catalog_books: %s", exc)
        return []
    finally:
        drv.close()


def record_borrow_transaction(
    book_snapshot: Optional[dict],
    borrower_id: str,
    borrower_name: str,
    borrow_at: str,
    due_at: str,
) -> bool:
    if not book_snapshot:
        return False
    borrower_id = (borrower_id or "").strip()
    borrower_name = (borrower_name or "").strip()
    borrow_at = (borrow_at or "").strip()
    due_at = (due_at or "").strip()
    if not (borrower_id and borrower_name and borrow_at and due_at):
        return False
    drv = _open_driver()
    if drv is None:
        return False
    bk = str(book_snapshot.get("book_key") or "").strip()
    lb_title = str(book_snapshot.get("lib_book") or "").strip()
    if not bk:
        return False
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            session.run(
                """
                CREATE (br:BorrowRecord {
                  borrower_id: $bid,
                  borrower_name: $bname,
                  book_key: $bk,
                  lib_book: $t,
                  borrow_at: $bat,
                  due_at: $dat,
                  returned_at: null,
                  created_at: datetime()
                })
                """,
                bid=borrower_id,
                bname=borrower_name,
                bk=bk,
                t=lb_title,
                bat=borrow_at,
                dat=due_at,
            )
        return True
    except Exception as exc:
        logger.warning("record_borrow_transaction: %s", exc)
        return False
    finally:
        drv.close()


def list_borrow_records(borrower_id: str, limit: int = 20) -> List[dict]:
    borrower_id = (borrower_id or "").strip()
    if not borrower_id:
        return []
    drv = _open_driver()
    if drv is None:
        return []
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            recs = session.run(
                """
                MATCH (br:BorrowRecord {borrower_id: $bid})
                RETURN br.book_key AS book_key,
                       br.lib_book AS lib_book,
                       br.borrower_id AS borrower_id,
                       br.borrower_name AS borrower_name,
                       br.borrow_at AS borrow_at,
                       br.due_at AS due_at,
                       CASE WHEN br.returned_at IS NULL THEN ''
                            ELSE toString(br.returned_at) END AS returned_at,
                       toString(br.created_at) AS created_at
                ORDER BY br.created_at DESC
                LIMIT $lim
                """,
                bid=borrower_id,
                lim=int(limit),
            )
            return [
                {
                    "book_key": str(r["book_key"] or "").strip(),
                    "lib_book": str(r["lib_book"] or "").strip(),
                    "borrower_id": str(r["borrower_id"] or "").strip(),
                    "borrower_name": str(r["borrower_name"] or "").strip(),
                    "borrow_at": str(r["borrow_at"] or "").strip(),
                    "due_at": str(r["due_at"] or "").strip(),
                    "returned_at": str(r["returned_at"] or "").strip(),
                    "created_at": str(r["created_at"] or "").strip(),
                }
                for r in recs
            ]
    except Exception as exc:
        logger.warning("list_borrow_records: %s", exc)
        return []
    finally:
        drv.close()


def recommend_on_shelf(topic: Optional[str], limit: int = 5) -> List[dict]:
    topic = (topic or "").strip()
    if not topic:
        return []
    drv = _open_driver()
    if drv is None:
        return []
    try:
        with drv.session() as session:
            _ensure_bootstrap_with_session(session)
            recs = session.run(
                """
                MATCH (lb:LibraryBook)
                WHERE lb.is_borrow = 0 AND lb.lib_book CONTAINS $t
                RETURN lb.book_key AS book_key,
                       lb.lib_book AS lib_book,
                       lb.book_pos AS book_pos,
                       coalesce(lb.summary, '') AS summary
                ORDER BY lb.lib_book
                LIMIT $lim
                """,
                t=topic,
                lim=int(limit),
            )
            return [dict(r) for r in recs]
    except Exception as exc:
        logger.warning("recommend_on_shelf: %s", exc)
        return []
    finally:
        drv.close()
