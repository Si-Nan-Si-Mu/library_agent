"""
自然语言 → Cypher：供 GraphRAG 调用；图谱执行在 actions.neo4j_graph.run_read_cypher（只读事务）。
"""
from __future__ import annotations

import re
from typing import Optional


def extract_cypher_from_model_output(text: str) -> Optional[str]:
    """从模型回复中提取单条只读 Cypher；无法解析或与安全规则冲突时返回 None。"""
    if not text:
        return None
    raw = text.strip()

    m = re.search(r"```(?:cypher)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    if m:
        q = m.group(1).strip()
    else:
        body_lines = []
        for ln in raw.splitlines():
            s = ln.strip()
            if not s or s.startswith("//"):
                continue
            body_lines.append(s)
        body = "\n".join(body_lines).strip()
        if re.match(r"^(MATCH|OPTIONAL\s+MATCH)\b", body, flags=re.IGNORECASE):
            q = body
        else:
            return None

    q = q.split(";")[0].strip()
    if not q:
        return None

    upper = f" {q.upper()} "
    forbidden = (
        " CREATE ",
        " MERGE ",
        " DELETE ",
        " DETACH ",
        " SET ",
        " REMOVE ",
        " DROP ",
        " LOAD CSV",
        " CALL ",
        " DBMS.",
        " ADMIN",
        " PASSWORD ",
    )
    if any(x in upper for x in forbidden):
        return None
    if "MATCH" not in q.upper():
        return None
    return q


def build_nl2cypher_user_message(question: str) -> str:
    """用户侧说明：把自然语言问题交给模型生成 Cypher。"""
    q = (question or "").strip()
    return (
        "用户问题如下，请按要求只输出 ```cypher 代码块。\n\n"
        f"【用户问题】\n{q if q else '（空）'}\n"
    )
