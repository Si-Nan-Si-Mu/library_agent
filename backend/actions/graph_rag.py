"""GraphRAG：NL2Cypher（DeepSeek）+ Neo4j 只读检索，将图谱事实拼入后续 LLM 回答。"""
from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from kg_module.neo4j_auth import neo4j_use_graph
from kg_module.nl2cypher import build_nl2cypher_user_message, extract_cypher_from_model_output
from kg_module.prompt_templates import NL2CYPHER_SYSTEM

from .deepseek_client import deepseek_chat
from .neo4j_graph import run_read_cypher

logger = logging.getLogger(__name__)


def graph_rag_enabled() -> bool:
    if (os.environ.get("GRAPH_RAG_DISABLED") or "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    if not neo4j_use_graph():
        return False
    if not (os.environ.get("DEEPSEEK_API_KEY") or "").strip():
        return False
    return True


def _should_attempt_graph_for_question(question: str) -> bool:
    """
    避免纯政策/闲聊类问题多走一轮 NL2Cypher。
    GRAPH_RAG_ALWAYS=1 时对任意非空问题都尝试图谱检索。
    """
    if (os.environ.get("GRAPH_RAG_ALWAYS") or "").strip().lower() in ("1", "true", "yes", "on"):
        return bool((question or "").strip())
    q = (question or "").strip()
    if len(q) < 4:
        return False
    keys = (
        "书",
        "图书",
        "书目",
        "作者",
        "写过",
        "主题",
        "类目",
        "分类",
        "图谱",
        "推荐",
        "哪本",
        "是谁",
        "小说",
        "文学",
        "诗集",
        "科幻",
        "推理",
        "简介",
        "介绍",
        "生平",
        "梗概",
        "内容",
    )
    return any(k in q for k in keys)


def _json_fallback(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _records_to_evidence(rows: List[Dict[str, Any]], max_chars: int) -> str:
    """将查询结果序列化为短文，便于主模型引用。"""
    if not rows:
        return ""
    compact: List[Dict[str, Any]] = []
    for r in rows:
        flat: Dict[str, Any] = {}
        for k, v in (r or {}).items():
            if v is None:
                continue
            if isinstance(v, str):
                s = v.strip()
                if len(s) > 400:
                    s = s[:380] + "…"
                flat[str(k)] = s
            else:
                flat[str(k)] = v
        compact.append(flat)

    blob = json.dumps(compact, ensure_ascii=False, default=_json_fallback)
    if len(blob) <= max_chars:
        return blob
    return blob[: max_chars - 20] + "…（截断）"


def graph_rag_retrieve_evidence(user_question: str) -> Tuple[str, Optional[str]]:
    """
    对用户问题做一次 NL2Cypher + 只读执行，返回可被主提示词消费的证据字符串。
    第二项为可选错误码：无图谱/无密钥时返回 ('', None) 表示静默跳过；生成或执行失败时非空。
    """
    q = (user_question or "").strip()
    if not q:
        return "", None

    if not graph_rag_enabled():
        return "", None

    if not _should_attempt_graph_for_question(q):
        return "", None

    nl_temp = os.environ.get("GRAPH_RAG_NL_TEMPERATURE")
    try:
        t_nl = float(nl_temp) if nl_temp is not None and str(nl_temp).strip() != "" else 0.15
    except ValueError:
        t_nl = 0.15

    raw, err = deepseek_chat(
        build_nl2cypher_user_message(q),
        system=NL2CYPHER_SYSTEM,
        temperature=t_nl,
        timeout=float(os.environ.get("GRAPH_RAG_NL_TIMEOUT") or "45"),
    )
    if err or not raw:
        logger.info("graph_rag: nl2cypher skipped (%s)", err or "empty")
        return "", err or "nl_empty"

    cypher = extract_cypher_from_model_output(raw)
    if not cypher:
        logger.info("graph_rag: no safe cypher extracted from model output")
        return "", "no_cypher"

    try:
        cap = int(os.environ.get("GRAPH_RAG_MAX_ROWS") or "80")
    except ValueError:
        cap = 80
    cap = max(5, min(cap, 120))

    rows, qerr = run_read_cypher(cypher, max_rows=cap)
    if qerr:
        return "", qerr

    if not rows:
        return "", None

    try:
        max_chars = int(os.environ.get("GRAPH_RAG_MAX_CONTEXT_CHARS") or "6000")
    except ValueError:
        max_chars = 6000
    max_chars = max(800, min(max_chars, 12000))

    return _records_to_evidence(rows, max_chars), None
