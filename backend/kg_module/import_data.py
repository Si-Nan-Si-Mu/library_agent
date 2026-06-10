"""从 CSV 批量导入 :LibraryBook（以 book_key 唯一）及 Author / Category / Topic 与关系到 Neo4j（与馆藏同一节点类型）。"""
import csv
import hashlib
import os
from typing import Optional

from env_bootstrap import load_repo_dotenv

load_repo_dotenv()

from neo4j import GraphDatabase

from neo4j_auth import driver_kwargs, resolve_auth

DEFAULT_URI = "bolt://localhost:7687"

IMPORT_CYPHER = """
MERGE (b:LibraryBook {book_key: $book_key})
SET b.lib_book = $title,
    b.title = $title,
    b.rating = $rating,
    b.summary = $summary,
    b.book_pos = CASE WHEN $apply_book_pos THEN $book_pos ELSE coalesce(b.book_pos, '') END,
    b.is_borrow = CASE WHEN $apply_is_borrow THEN $is_borrow ELSE coalesce(b.is_borrow, 0) END

MERGE (a:Author {name: $author})
SET a.bio = CASE WHEN trim(coalesce($bio, '')) <> '' THEN trim($bio) ELSE coalesce(a.bio, '') END
MERGE (b)-[:WRITTEN_BY]->(a)

MERGE (c:Category {name: $category})
MERGE (b)-[:BELONGS_TO]->(c)

MERGE (d:Discipline {name: $category})
MERGE (b)-[:IN_DISCIPLINE]->(d)

MERGE (t:Topic {name: $topic})
MERGE (b)-[:COVERS_TOPIC]->(t)
"""


def _parse_is_borrow_cell(raw: Optional[str]) -> Optional[int]:
    """CSV 借阅标识：空或未列出不返回（导入时不改）；0/1、true/false、在架/已借 等。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    if low in ("1", "true", "yes", "y", "是", "已借", "借出", "已借出"):
        return 1
    if low in ("0", "false", "no", "n", "否", "在架", "可借"):
        return 0
    try:
        n = int(float(s))
        return 1 if n != 0 else 0
    except (TypeError, ValueError):
        return None


def _driver():
    uri = (os.environ.get("NEO4J_URI") or DEFAULT_URI).strip()
    try:
        auth = resolve_auth()
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    return GraphDatabase.driver(uri, auth=auth, **driver_kwargs())


def clear_all_neo4j_demo_data() -> int:
    """
    删除演示/书目相关的全部 Neo4j 节点：:LibraryBook、:BorrowRecord、:Book（遗留）、:Author、:Category、:Topic、:Discipline。
    用于「清空后全量重导」；之后请运行 CSV 导入，并由本脚本在 --reset 流程末尾调用 ensure_bootstrap 重灌馆藏。
    返回 1 表示完成一轮清空。
    """
    driver = _driver()
    try:
        with driver.session() as session:
            for label in ("LibraryBook", "BorrowRecord", "Book", "Author", "Category", "Topic", "Discipline"):
                session.run(f"MATCH (n:{label}) DETACH DELETE n")
    finally:
        driver.close()
    return 1


def clear_book_knowledge_graph() -> int:
    """清空书目元数据节点与遗留 :Book，不删除 :LibraryBook / :BorrowRecord（移除 Author/Category/Topic 及其与馆藏的边）。"""
    driver = _driver()
    try:
        with driver.session() as session:
            session.run("MATCH (n:Book) DETACH DELETE n")
            session.run(
                """
                MATCH (n)
                WHERE n:Author OR n:Category OR n:Topic OR n:Discipline
                DETACH DELETE n
                """
            )
    finally:
        driver.close()
    return 1


def prune_orphan_library_books() -> None:
    """
    删除无任何 ``(:LibraryBook)-[:WRITTEN_BY]->(:Author)`` 的馆藏节点（历史 SEED 补条），
    并删除 ``book_key`` 指向已删副本的 ``:BorrowRecord``，以及无对应馆藏的流水。
    """
    driver = _driver()
    try:
        with driver.session() as session:
            session.run(
                """
                MATCH (lb:LibraryBook)
                WHERE NOT (lb)-[:WRITTEN_BY]->(:Author)
                MATCH (br:BorrowRecord {book_key: lb.book_key})
                DETACH DELETE br
                """
            )
            session.run(
                """
                MATCH (lb:LibraryBook)
                WHERE NOT (lb)-[:WRITTEN_BY]->(:Author)
                DETACH DELETE lb
                """
            )
            session.run(
                """
                MATCH (br:BorrowRecord)
                WHERE NOT EXISTS { MATCH (:LibraryBook {book_key: br.book_key}) }
                DETACH DELETE br
                """
            )
    finally:
        driver.close()


def import_csv_to_neo4j(csv_file_path: str) -> int:
    driver = _driver()
    success_count = 0
    try:
        with driver.session() as session:
            with open(csv_file_path, mode="r", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    title = (row.get("title") or "").strip()
                    raw_bk = (row.get("book_key") or "").strip()
                    if raw_bk:
                        book_key = raw_bk
                    else:
                        h = hashlib.md5(title.encode("utf-8")).hexdigest()[:12].upper()
                        book_key = f"KG.LEGACY.{h}"
                    raw_pos = row.get("book_pos")
                    book_pos_cell = (raw_pos if raw_pos is not None else "").strip()
                    apply_book_pos = bool(book_pos_cell)
                    ib = _parse_is_borrow_cell(row.get("is_borrow"))
                    apply_is_borrow = ib is not None
                    params = {
                        "book_key": book_key,
                        "title": title,
                        "author": row["author"],
                        "bio": (row.get("author_bio") or "").strip(),
                        "category": row["category"],
                        "topic": row["topic"],
                        "rating": float(row["rating"]),
                        "summary": row["summary"],
                        "apply_book_pos": apply_book_pos,
                        "book_pos": book_pos_cell,
                        "apply_is_borrow": apply_is_borrow,
                        "is_borrow": int(ib) if ib is not None else 0,
                    }
                    session.run(IMPORT_CYPHER, **params)
                    success_count += 1
                    print(f"已导入书籍: {book_key} 《{title}》")
    finally:
        driver.close()
    prune_orphan_library_books()
    try:
        from graph_networks import build_knowledge_networks

        net_stats = build_knowledge_networks()
        print(
            "知识网络：作者关系 CSV {author_relations_csv} 条；"
            "作者—学科 WORKS_IN {author_works_in}；"
            "主题—学科 {topic_under_discipline}；"
            "同学科 CONTEMPORARY_WITH {contemporary_by_discipline}。".format(**net_stats)
        )
    except Exception as exc:
        print(f"知识网络构建跳过或失败: {exc}")
    print(f"\n导入完成！共成功处理 {success_count} 本书籍。")
    return success_count


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if "--prune-orphans-only" in sys.argv:
        prune_orphan_library_books()
        print("已修剪无图谱边的孤立 LibraryBook 及无效 BorrowRecord（如有）。")
        raise SystemExit(0)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(current_dir, "raw_data", "books.csv")
    graph_only = "--graph-only" in sys.argv

    if "--reset" in sys.argv or "-r" in sys.argv:
        if graph_only:
            print(
                "正在清空 Author / Category / Topic / Discipline 与遗留 :Book（保留 LibraryBook、BorrowRecord）…"
            )
            clear_book_knowledge_graph()
        else:
            print(
                "正在清空 Neo4j 演示数据：LibraryBook、BorrowRecord、遗留 Book、Author、Category、Topic、Discipline …"
            )
            clear_all_neo4j_demo_data()
        print("清空完成。")
    print(f"开始读取文件: {csv_path}")
    import_csv_to_neo4j(csv_path)
    if ("--reset" in sys.argv or "-r" in sys.argv) and not graph_only:
        print("正在重新写入馆藏约束与 :LibraryBook 演示种子…")
        backend_root = Path(__file__).resolve().parent.parent
        root_str = str(backend_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        try:
            from actions.neo4j_library_store import ensure_bootstrap

            if ensure_bootstrap():
                print("馆藏演示数据已就绪。")
            else:
                print(
                    "馆藏未写入：请检查 NEO4J_* 配置后执行 python scripts/seed_library_graph.py"
                )
        except Exception as exc:
            print(f"馆藏补种失败: {exc}")
            print("请手动在 backend 目录执行: python scripts/seed_library_graph.py")
        prune_orphan_library_books()
        print("已修剪无图谱边的孤立 LibraryBook 及无效 BorrowRecord（如有）。")
