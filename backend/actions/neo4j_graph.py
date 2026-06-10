"""Neo4j 书目图谱：主题/学科推荐、作者关系网络、只读 Cypher。"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from kg_module.neo4j_auth import driver_kwargs, neo4j_use_graph, resolve_auth

from .neo4j_library_store import expand_topic_search_terms

logger = logging.getLogger(__name__)

DEFAULT_URI = "bolt://localhost:7687"


def _related_author_names(author_name: str, limit: int = 4) -> List[str]:
    """作者关系网络：取与指定作者有直接关系的其他作者名。"""
    name = (author_name or "").strip()
    if not name or not neo4j_use_graph():
        return []
    try:
        from kg_module.graph_networks import fetch_author_network
    except ImportError:
        return []
    peers: List[str] = []
    for item in fetch_author_network(name, limit=limit + 2):
        peer = str(item.get("peer") or "").strip()
        if peer and peer != name and peer not in peers:
            peers.append(peer)
        if len(peers) >= limit:
            break
    return peers


def neo4j_configured() -> bool:
    return neo4j_use_graph()


def _rank_graph_candidates(
    terms: List[str],
    rows: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """按主题词命中质量排序：越靠前的扩展词权重越高；题名精确含主题优先。"""
    if not rows:
        return []

    def score(rec: Dict[str, Any]) -> Tuple[int, float, str]:
        title = str(rec.get("title") or "")
        authors = rec.get("authors") or []
        topics = rec.get("topics") or []
        categories = rec.get("categories") or []
        disciplines = rec.get("disciplines") or []
        if not isinstance(authors, list):
            authors = []
        if not isinstance(topics, list):
            topics = []
        if not isinstance(categories, list):
            categories = []
        if not isinstance(disciplines, list):
            disciplines = []
        best_term = 999
        kind_bonus = 0
        lt = title.lower()
        for i, term in enumerate(terms):
            if not term:
                continue
            tl = term.lower()
            if tl and tl in lt:
                best_term = min(best_term, i)
                kind_bonus = max(kind_bonus, 4)
            for x in topics:
                xs = str(x or "").lower()
                if xs and (tl in xs or xs in tl):
                    best_term = min(best_term, i)
                    kind_bonus = max(kind_bonus, 3)
            for x in disciplines:
                xs = str(x or "").lower()
                if xs and (tl in xs or xs in tl):
                    best_term = min(best_term, i)
                    kind_bonus = max(kind_bonus, 3)
            for x in authors:
                xs = str(x or "").lower()
                if xs and (tl in xs or xs in tl):
                    best_term = min(best_term, i)
                    kind_bonus = max(kind_bonus, 2)
            for x in categories:
                xs = str(x or "").lower()
                if xs and (tl in xs or xs in tl):
                    best_term = min(best_term, i)
                    kind_bonus = max(kind_bonus, 1)
        if best_term == 999:
            best_term = 500
        rating = rec.get("rating")
        try:
            rf = float(rating) if rating is not None else 0.0
        except (TypeError, ValueError):
            rf = 0.0
        return (-kind_bonus, best_term, -rf, title)

    ranked = sorted(rows, key=score)
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for rec in ranked:
        bk = str(rec.get("book_key") or "").strip()
        title = str(rec.get("title") or "").strip()
        dedupe_key = bk or title
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(rec)
        if len(out) >= int(limit):
            break
    return out


def recommend_books_by_topic(topic: str, limit: int = 8) -> List[Dict[str, Any]]:
    """
    按主题从图谱取书：匹配 Topic / Discipline / Category / Author / 书名。
    返回 dict 含 title, rating, summary, authors, topics, categories, disciplines, author_bios, related_authors。
    """
    q = (topic or "").strip()
    if not q or not neo4j_use_graph():
        return []
    terms = expand_topic_search_terms(q)
    if not terms:
        terms = [q]
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
    MATCH (b:LibraryBook)
    OPTIONAL MATCH (b)-[:WRITTEN_BY]->(a:Author)
    OPTIONAL MATCH (b)-[:BELONGS_TO]->(c:Category)
    OPTIONAL MATCH (b)-[:IN_DISCIPLINE]->(d:Discipline)
    OPTIONAL MATCH (b)-[:COVERS_TOPIC]->(t:Topic)
    WITH b, collect(DISTINCT a) AS anodes, collect(DISTINCT c) AS cnodes,
         collect(DISTINCT d) AS dnodes, collect(DISTINCT t) AS tnodes
    WITH b,
         [x IN anodes WHERE x IS NOT NULL
            | {name: coalesce(x.name, ''), bio: coalesce(x.bio, '')}] AS author_parts,
         [x IN cnodes WHERE x IS NOT NULL | x.name] AS categories,
         [x IN dnodes WHERE x IS NOT NULL | x.name] AS disciplines,
         [x IN tnodes WHERE x IS NOT NULL | x.name] AS topics
    WITH b, author_parts, categories, disciplines, topics,
         [p IN author_parts | p.name] AS authors
    WITH b, author_parts, categories, disciplines, topics, authors,
         trim(coalesce(b.lib_book, b.title, '')) AS disp_title
    WHERE ANY(term IN $terms
          WHERE toLower(coalesce(b.book_key, '')) CONTAINS toLower(term)
             OR toLower(disp_title) CONTAINS toLower(term)
             OR toLower(term) CONTAINS toLower(disp_title)
             OR toLower(coalesce(b.summary, '')) CONTAINS toLower(term)
             OR ANY(x IN authors WHERE x <> '' AND toLower(x) CONTAINS toLower(term))
             OR ANY(x IN topics WHERE x IS NOT NULL AND x <> '' AND (
                   toLower(x) CONTAINS toLower(term) OR toLower(term) CONTAINS toLower(x)))
             OR ANY(x IN disciplines WHERE x IS NOT NULL AND x <> '' AND (
                   toLower(x) CONTAINS toLower(term) OR toLower(term) CONTAINS toLower(x)))
             OR ANY(x IN categories WHERE x IS NOT NULL AND x <> '' AND (
                   toLower(x) CONTAINS toLower(term) OR toLower(term) CONTAINS toLower(x))))
    RETURN b.book_key AS book_key,
           disp_title AS title,
           b.rating AS rating,
           coalesce(b.summary, '') AS summary,
           author_parts,
           categories,
           disciplines,
           topics
    LIMIT $fetch_limit
    """

    raw_rows: List[Dict[str, Any]] = []
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=auth, **driver_kwargs())
        with driver.session() as session:
            result = session.run(
                cypher,
                terms=terms,
                fetch_limit=min(120, int(limit) * 15),
            )
            for record in result:
                data = record.data()
                parts = data.get("author_parts") or []
                authors: List[str] = []
                author_bios: List[str] = []
                for p in parts:
                    if not isinstance(p, dict):
                        continue
                    name = str(p.get("name") or "").strip()
                    if not name:
                        continue
                    authors.append(name)
                    author_bios.append(str(p.get("bio") or "").strip())
                related_authors: List[str] = []
                for an in authors[:2]:
                    related_authors.extend(_related_author_names(an, limit=4))
                raw_rows.append(
                    {
                        "book_key": str(data.get("book_key") or "").strip(),
                        "title": data.get("title"),
                        "rating": data.get("rating"),
                        "summary": (data.get("summary") or "").strip(),
                        "authors": authors,
                        "author_bios": author_bios,
                        "categories": [str(x) for x in (data.get("categories") or []) if x],
                        "disciplines": [str(x) for x in (data.get("disciplines") or []) if x],
                        "topics": [str(x) for x in (data.get("topics") or []) if x],
                        "related_authors": list(dict.fromkeys(related_authors))[:8],
                    }
                )
    except Exception as exc:  # pragma: no cover
        logger.warning("recommend_books_by_topic: %s", exc)
        return []
    finally:
        if driver is not None:
            driver.close()

    return _rank_graph_candidates(terms, raw_rows, limit)


def run_read_cypher(
    cypher: str,
    parameters: Optional[Dict[str, Any]] = None,
    *,
    max_rows: int = 80,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    在只读事务中执行 Cypher，供 GraphRAG / NL2Cypher 使用。
    返回 (行字典列表, 错误码)；成功时错误码为 None。
    """
    stmt = (cypher or "").strip()
    if not stmt or not neo4j_use_graph():
        return [], "skip" if not stmt else "neo4j_off"

    try:
        from neo4j import READ_ACCESS, GraphDatabase
    except ImportError:
        return [], "no_driver"

    try:
        auth = resolve_auth()
    except ValueError:
        return [], "no_auth"

    uri = (os.environ.get("NEO4J_URI") or DEFAULT_URI).strip()
    params = parameters or {}
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=auth, **driver_kwargs())
        with driver.session(default_access_mode=READ_ACCESS) as session:
            result = session.run(stmt, params)
            rows: List[Dict[str, Any]] = []
            for record in result:
                rows.append(record.data())
                if len(rows) >= int(max_rows):
                    break
            return rows, None
    except Exception as exc:  # pragma: no cover - 驱动/语法错误
        logger.warning("run_read_cypher: %s", exc)
        return [], f"query_error:{type(exc).__name__}"
    finally:
        if driver is not None:
            driver.close()
