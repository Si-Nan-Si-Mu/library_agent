"""作者关系网络与学科关系网络：导入、派生边与只读查询辅助。"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from env_bootstrap import load_repo_dotenv

load_repo_dotenv()

from neo4j import GraphDatabase

from neo4j_auth import driver_kwargs, resolve_auth

DEFAULT_URI = "bolt://localhost:7687"

VALID_AUTHOR_REL_TYPES = frozenset(
    {"INFLUENCED", "CONTEMPORARY_WITH", "RIVAL_OF", "SHARES_DISCIPLINE_WITH"}
)

# 同一学科下作者两两建立「同时代/同领域」边的上限（避免完全图爆炸）
MAX_CONTEMPORARY_PAIRS_PER_DISCIPLINE = 28


def _driver():
    uri = (os.environ.get("NEO4J_URI") or DEFAULT_URI).strip()
    auth = resolve_auth()
    return GraphDatabase.driver(uri, auth=auth, **driver_kwargs())


def _raw_data_dir() -> Path:
    return Path(__file__).resolve().parent / "raw_data"


def import_author_relations_csv(csv_path: Optional[str] = None) -> int:
    """从 CSV 导入作者—作者关系（需在 Author 节点已存在后调用）。"""
    path = Path(csv_path) if csv_path else _raw_data_dir() / "author_relations.csv"
    if not path.is_file():
        return 0
    count = 0
    driver = _driver()
    try:
        with driver.session() as session, path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                src = (row.get("source_author") or "").strip()
                tgt = (row.get("target_author") or "").strip()
                rel = (row.get("relation_type") or "").strip().upper()
                note = (row.get("note") or "").strip()
                if not src or not tgt or src == tgt:
                    continue
                if rel not in VALID_AUTHOR_REL_TYPES:
                    continue
                if rel == "CONTEMPORARY_WITH":
                    session.run(
                        """
                        MATCH (a:Author {name: $src}), (b:Author {name: $tgt})
                        MERGE (a)-[r:CONTEMPORARY_WITH]-(b)
                        SET r.note = $note
                        """,
                        src=src,
                        tgt=tgt,
                        note=note,
                    )
                else:
                    session.run(
                        f"""
                        MATCH (a:Author {{name: $src}}), (b:Author {{name: $tgt}})
                        MERGE (a)-[r:{rel}]->(b)
                        SET r.note = $note
                        """,
                        src=src,
                        tgt=tgt,
                        note=note,
                    )
                count += 1
    finally:
        driver.close()
    return count


def derive_author_discipline_links() -> int:
    """由图书—作者—学科推导 (Author)-[:WORKS_IN]->(Discipline)。"""
    driver = _driver()
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (b:LibraryBook)-[:WRITTEN_BY]->(a:Author)
                MATCH (b)-[:IN_DISCIPLINE]->(d:Discipline)
                MERGE (a)-[r:WORKS_IN]->(d)
                RETURN count(r) AS c
                """
            )
            rec = result.single()
            return int(rec["c"] or 0) if rec else 0
    finally:
        driver.close()


def derive_topic_discipline_links() -> int:
    """由图书同时覆盖的主题与学科，建立 (Topic)-[:UNDER_DISCIPLINE]->(Discipline)。"""
    driver = _driver()
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (b:LibraryBook)-[:COVERS_TOPIC]->(t:Topic)
                MATCH (b)-[:IN_DISCIPLINE]->(d:Discipline)
                MERGE (t)-[r:UNDER_DISCIPLINE]->(d)
                RETURN count(r) AS c
                """
            )
            rec = result.single()
            return int(rec["c"] or 0) if rec else 0
    finally:
        driver.close()


def derive_contemporary_by_discipline(max_pairs: int = MAX_CONTEMPORARY_PAIRS_PER_DISCIPLINE) -> int:
    """同一学科、著作≥1 的作者之间补充 CONTEMPORARY_WITH（演示用，已有则跳过）。"""
    driver = _driver()
    created = 0
    try:
        with driver.session() as session:
            disciplines = session.run(
                """
                MATCH (d:Discipline)<-[:IN_DISCIPLINE]-(:LibraryBook)-[:WRITTEN_BY]->(a:Author)
                WITH d, collect(DISTINCT a.name) AS names
                WHERE size(names) >= 2
                RETURN d.name AS discipline, names AS names
                """
            )
            for rec in disciplines:
                names = sorted({str(n).strip() for n in (rec["names"] or []) if str(n).strip()})
                pairs = 0
                for i, n1 in enumerate(names):
                    if pairs >= max_pairs:
                        break
                    for n2 in names[i + 1 :]:
                        if pairs >= max_pairs:
                            break
                        session.run(
                            """
                            MATCH (a:Author {name: $n1}), (b:Author {name: $n2})
                            MERGE (a)-[r:CONTEMPORARY_WITH]-(b)
                            ON CREATE SET r.note = $note
                            """,
                            n1=n1,
                            n2=n2,
                            note=f"同属学科「{rec['discipline']}」",
                        )
                        pairs += 1
                        created += 1
    finally:
        driver.close()
    return created


def build_knowledge_networks(author_relations_csv: Optional[str] = None) -> Dict[str, int]:
    """在 books.csv 导入后调用：作者关系 CSV + 学科网络派生边。"""
    stats = {
        "author_relations_csv": import_author_relations_csv(author_relations_csv),
        "author_works_in": derive_author_discipline_links(),
        "topic_under_discipline": derive_topic_discipline_links(),
        "contemporary_by_discipline": derive_contemporary_by_discipline(),
    }
    return stats


def fetch_author_network(name: str, limit: int = 12) -> List[Dict[str, Any]]:
    """查询某作者的关系网络（出边与入边）。"""
    name = (name or "").strip()
    if not name:
        return []
    driver = _driver()
    rows: List[Dict[str, Any]] = []
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (a:Author {name: $name})
                OPTIONAL MATCH (a)-[r_out]->(other_out:Author)
                WHERE type(r_out) IN $rel_types
                OPTIONAL MATCH (other_in:Author)-[r_in]->(a)
                WHERE type(r_in) IN $rel_types
                WITH a,
                     collect(DISTINCT {
                         direction: 'out',
                         relation: type(r_out),
                         peer: other_out.name,
                         peer_bio: coalesce(other_out.bio, ''),
                         note: coalesce(r_out.note, '')
                     }) AS outs,
                     collect(DISTINCT {
                         direction: 'in',
                         relation: type(r_in),
                         peer: other_in.name,
                         peer_bio: coalesce(other_in.bio, ''),
                         note: coalesce(r_in.note, '')
                     }) AS ins
                RETURN outs, ins
                """,
                name=name,
                rel_types=list(VALID_AUTHOR_REL_TYPES),
            )
            rec = result.single()
            if not rec:
                return []
            for item in (rec["outs"] or []) + (rec["ins"] or []):
                if not item or not item.get("peer"):
                    continue
                rows.append(item)
                if len(rows) >= limit:
                    break
    finally:
        driver.close()
    return rows


def fetch_discipline_bundle(discipline_name: str, book_limit: int = 20) -> Dict[str, Any]:
    """学科视角：学科节点、关联作者、在馆书目摘要。"""
    discipline_name = (discipline_name or "").strip()
    if not discipline_name:
        return {}
    driver = _driver()
    try:
        with driver.session() as session:
            disc = session.run(
                """
                MATCH (d:Discipline)
                WHERE toLower(d.name) = toLower($name)
                   OR toLower(d.name) CONTAINS toLower($name)
                RETURN d.name AS name, coalesce(d.description, '') AS description
                LIMIT 1
                """,
                name=discipline_name,
            ).single()
            if not disc:
                return {}
            dname = disc["name"]
            authors = session.run(
                """
                MATCH (a:Author)-[:WORKS_IN]->(d:Discipline {name: $dname})
                RETURN a.name AS name, coalesce(a.bio, '') AS bio
                ORDER BY a.name
                LIMIT 40
                """,
                dname=dname,
            )
            books = session.run(
                """
                MATCH (b:LibraryBook)-[:IN_DISCIPLINE]->(d:Discipline {name: $dname})
                OPTIONAL MATCH (b)-[:WRITTEN_BY]->(a:Author)
                RETURN b.book_key AS book_key,
                       coalesce(b.lib_book, b.title, '') AS title,
                       coalesce(b.summary, '') AS summary,
                       coalesce(b.book_pos, '') AS book_pos,
                       b.is_borrow AS is_borrow,
                       collect(DISTINCT a.name) AS authors
                ORDER BY title
                LIMIT $lim
                """,
                dname=dname,
                lim=int(book_limit),
            )
            return {
                "discipline": dname,
                "description": disc["description"] or "",
                "authors": [dict(r) for r in authors],
                "books": [dict(r) for r in books],
            }
    finally:
        driver.close()


if __name__ == "__main__":
    import sys

    stats = build_knowledge_networks()
    print("知识网络构建完成:", stats)
