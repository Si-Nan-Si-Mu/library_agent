"""在 Neo4j 中创建与 kg 导入一致的约束（Neo4j 5 语法）。"""
import os

from env_bootstrap import load_repo_dotenv

load_repo_dotenv()

from neo4j import GraphDatabase

from neo4j_auth import driver_kwargs, resolve_auth

DEFAULT_URI = "bolt://localhost:7687"

SCHEMA_QUERIES = [
    "DROP CONSTRAINT book_title IF EXISTS;",
    "DROP CONSTRAINT book_book_key IF EXISTS;",
    "CREATE CONSTRAINT author_name IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE;",
    "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE;",
    "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE;",
    "CREATE CONSTRAINT library_book_key IF NOT EXISTS FOR (lb:LibraryBook) REQUIRE lb.book_key IS UNIQUE;",
]


def init_schema() -> None:
    uri = (os.environ.get("NEO4J_URI") or DEFAULT_URI).strip()
    try:
        auth = resolve_auth()
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    print("正在连接 Neo4j 数据库")
    driver = GraphDatabase.driver(uri, auth=auth, **driver_kwargs())
    try:
        with driver.session() as session:
            for query in SCHEMA_QUERIES:
                try:
                    session.run(query)
                    print(f"执行成功: {query.split('IF NOT EXISTS FOR')[0].strip()}")
                except Exception as e:
                    print(f"执行失败: {e}")
    finally:
        driver.close()
    print("图谱约束初始化完成！")


if __name__ == "__main__":
    init_schema()
