"""
图谱 Cypher 查询封装层（构成对齐 library-RAG-Rasa 仓库的 actions/neo4j_connector.py）。

与参考仓库的差异：
- 连接信息来自本地 `.env`（kg_module.neo4j_auth），不在代码中硬编码账号密码；
- 书目节点为本地的 :LibraryBook（book_key 唯一，含馆藏属性），而非 :Book；
- 主题匹配额外覆盖 :Discipline（学科网络）；作者关系查询带 note 属性。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from kg_module.neo4j_auth import driver_kwargs, neo4j_use_graph, resolve_auth

logger = logging.getLogger(__name__)

DEFAULT_URI = "bolt://localhost:7687"


def _driver():
    from neo4j import GraphDatabase

    uri = (os.environ.get("NEO4J_URI") or DEFAULT_URI).strip()
    return GraphDatabase.driver(uri, auth=resolve_auth(), **driver_kwargs())


def get_books_by_topic(topic_name: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    按主题/类目/学科检索书籍，按评分降序（对齐参考仓库 get_books_by_topic）。
    返回中文键 dict 列表：书名 / 评分 / 简介 / 作者 / 索书号 / 是否在架。
    """
    topic_name = (topic_name or "").strip()
    if not topic_name or not neo4j_use_graph():
        return []

    cypher_query = """
    MATCH (b:LibraryBook)-[:COVERS_TOPIC|BELONGS_TO|IN_DISCIPLINE]->(node)
    WHERE node.name CONTAINS $topic
    OPTIONAL MATCH (b)-[:WRITTEN_BY]->(a:Author)
    RETURN DISTINCT
        coalesce(b.lib_book, b.title, '') AS title,
        b.rating AS rating,
        coalesce(b.summary, '') AS summary,
        coalesce(b.book_key, '') AS book_key,
        coalesce(b.is_borrow, 0) AS is_borrow,
        collect(DISTINCT a.name) AS authors
    ORDER BY rating DESC
    LIMIT $limit
    """

    results: List[Dict[str, Any]] = []
    driver = None
    try:
        driver = _driver()
        with driver.session() as session:
            records = session.run(cypher_query, topic=topic_name, limit=int(limit))
            for record in records:
                results.append(
                    {
                        "书名": record["title"],
                        "评分": record["rating"],
                        "简介": record["summary"],
                        "作者": [x for x in (record["authors"] or []) if x],
                        "索书号": record["book_key"],
                        "是否在架": "在架可借" if int(record["is_borrow"] or 0) == 0 else "已借出",
                    }
                )
    except Exception as exc:  # pragma: no cover
        logger.warning("get_books_by_topic: %s", exc)
        return []
    finally:
        if driver is not None:
            driver.close()
    return results


def get_author_profile(author_name: str) -> Optional[Dict[str, Any]]:
    """
    模糊检索作者档案（对齐参考仓库 get_author_profile）：
    忽略「·」分隔符的包含匹配；返回 姓名 / 主要领域 / 简介 / 馆藏著作 / 学术与人物关联。
    """
    author_name = (author_name or "").strip()
    if not author_name or not neo4j_use_graph():
        return None

    cypher_query = """
    MATCH (a:Author)
    WHERE a.name CONTAINS $author
       OR replace(a.name, '·', '') CONTAINS replace($author, '·', '')
    OPTIONAL MATCH (b:LibraryBook)-[:WRITTEN_BY]->(a)
    OPTIONAL MATCH (a)-[r]-(related:Author)
    OPTIONAL MATCH (a)-[:WORKS_IN]->(d:Discipline)
    RETURN
        a.name AS name,
        coalesce(a.primary_field, '') AS field,
        coalesce(a.bio, '') AS bio,
        collect(DISTINCT coalesce(b.lib_book, b.title)) AS books,
        collect(DISTINCT {
            relation_type: type(r),
            related_author: related.name,
            note: coalesce(r.note, '')
        }) AS connections,
        collect(DISTINCT d.name) AS disciplines
    LIMIT 1
    """

    profile: Optional[Dict[str, Any]] = None
    driver = None
    try:
        driver = _driver()
        with driver.session() as session:
            record = session.run(cypher_query, author=author_name).single()
            if record and record["name"]:
                connections = [
                    c
                    for c in (record["connections"] or [])
                    if c and c.get("related_author") and c.get("relation_type") not in ("WORKS_IN",)
                ]
                field = record["field"] or "、".join(
                    x for x in (record["disciplines"] or []) if x
                )
                profile = {
                    "姓名": record["name"],
                    "主要领域": field,
                    "简介": record["bio"],
                    "馆藏著作": [x for x in (record["books"] or []) if x],
                    "学术/人物关联": connections,
                }
    except Exception as exc:  # pragma: no cover
        logger.warning("get_author_profile: %s", exc)
        return None
    finally:
        if driver is not None:
            driver.close()
    return profile
