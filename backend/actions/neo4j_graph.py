"""Neo4j 主题推荐（与 kg_module 导入的 Book–Topic 结构一致）。未配置密码或未安装驱动时返回空列表。"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from kg_module.neo4j_auth import driver_kwargs, neo4j_use_graph, resolve_auth

DEFAULT_URI = "bolt://localhost:7687"


def neo4j_configured() -> bool:
    return neo4j_use_graph()


def recommend_books_by_topic(topic: str, limit: int = 8) -> List[Dict[str, Any]]:
    """按主题从图谱取书；失败或未配置时返回 []。"""
    q = (topic or "").strip()
    if not q or not neo4j_use_graph():
        return []
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return []

    try:
        auth = resolve_auth()
    except ValueError:
        return []

    uri = (os.environ.get("NEO4J_URI") or DEFAULT_URI).strip()

    cypher = """
    MATCH (b:Book)-[:COVERS_TOPIC]->(t:Topic)
    WHERE toLower(t.name) CONTAINS toLower($topic)
       OR toLower($topic) CONTAINS toLower(t.name)
       OR toLower(b.title) CONTAINS toLower($topic)
    RETURN b.title AS title,
           b.rating AS rating,
           coalesce(b.summary, '') AS summary
    ORDER BY b.rating DESC
    LIMIT $fetch_limit
    """

    rows: List[Dict[str, Any]] = []
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=auth, **driver_kwargs())
        with driver.session() as session:
            result = session.run(cypher, topic=q, fetch_limit=min(50, int(limit) * 5))
            seen: set[str] = set()
            for record in result:
                title = record["title"]
                if not title or title in seen:
                    continue
                seen.add(title)
                rows.append(
                    {
                        "title": title,
                        "rating": record["rating"],
                        "summary": (record["summary"] or "").strip(),
                    }
                )
                if len(rows) >= int(limit):
                    break
    except Exception:
        return []
    finally:
        if driver is not None:
            driver.close()
    return rows
