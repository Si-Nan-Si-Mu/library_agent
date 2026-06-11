"""Neo4j 鉴权：密码模式，或本地无鉴权测试（NEO4J_AUTH_NONE=1 + driver auth=None）。"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple, Union

AuthArg = Union[Tuple[str, str], None]


def no_auth_test_mode() -> bool:
    return (os.environ.get("NEO4J_AUTH_NONE") or "").strip().lower() in ("1", "true", "yes", "on")


def neo4j_use_graph() -> bool:
    """是否走图谱（有密码，或显式开启无鉴权测试）。"""
    if (os.environ.get("NEO4J_PASSWORD") or "").strip():
        return True
    return no_auth_test_mode()


def resolve_auth() -> AuthArg:
    """
    供 GraphDatabase.driver(uri, auth=...) 使用。
    - 有 NEO4J_PASSWORD：basic (USER, PASSWORD)
    - 无密码且 NEO4J_AUTH_NONE=1：None（要求 Neo4j 以关闭鉴权方式运行，如 docker -e NEO4J_AUTH=none）
    """
    # 兼容两种变量名：NEO4J_USER（本项目）与 NEO4J_USERNAME（Aura 下载的凭据文件）
    user = (
        os.environ.get("NEO4J_USER")
        or os.environ.get("NEO4J_USERNAME")
        or "neo4j"
    ).strip()
    password = (os.environ.get("NEO4J_PASSWORD") or "").strip()
    if password:
        return (user, password)
    if no_auth_test_mode():
        return None
    raise ValueError(
        "Neo4j：请设置 NEO4J_PASSWORD；若为本地无鉴权测试，请在 .env 中设置 NEO4J_AUTH_NONE=1，"
        "并确保实例已关闭鉴权（例如 Docker 使用 NEO4J_AUTH=none）。"
    )


def driver_kwargs() -> Dict[str, Any]:
    """传给 GraphDatabase.driver 的额外参数（可按驱动版本扩展）。"""
    return {}
