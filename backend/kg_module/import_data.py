"""从 CSV 批量导入 Book / Author / Category / Topic 节点与关系到 Neo4j。"""
import csv
import os

from env_bootstrap import load_repo_dotenv

load_repo_dotenv()

from neo4j import GraphDatabase

from neo4j_auth import driver_kwargs, resolve_auth

DEFAULT_URI = "bolt://localhost:7687"

IMPORT_CYPHER = """
MERGE (b:Book {title: $title})
SET b.rating = $rating, b.summary = $summary

MERGE (a:Author {name: $author})
MERGE (b)-[:WRITTEN_BY]->(a)

MERGE (c:Category {name: $category})
MERGE (b)-[:BELONGS_TO]->(c)

MERGE (t:Topic {name: $topic})
MERGE (b)-[:COVERS_TOPIC]->(t)
"""


def _driver():
    uri = (os.environ.get("NEO4J_URI") or DEFAULT_URI).strip()
    try:
        auth = resolve_auth()
    except ValueError as e:
        raise RuntimeError(str(e)) from e
    return GraphDatabase.driver(uri, auth=auth, **driver_kwargs())


def import_csv_to_neo4j(csv_file_path: str) -> int:
    driver = _driver()
    success_count = 0
    try:
        with driver.session() as session:
            with open(csv_file_path, mode="r", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    params = {
                        "title": row["title"],
                        "author": row["author"],
                        "category": row["category"],
                        "topic": row["topic"],
                        "rating": float(row["rating"]),
                        "summary": row["summary"],
                    }
                    session.run(IMPORT_CYPHER, **params)
                    success_count += 1
                    print(f"已导入书籍: 《{row['title']}》")
    finally:
        driver.close()
    print(f"\n导入完成！共成功处理 {success_count} 本书籍。")
    return success_count


if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(current_dir, "raw_data", "books.csv")
    print(f"开始读取文件: {csv_path}")
    import_csv_to_neo4j(csv_path)
