#!/usr/bin/env python3
"""
触发 Neo4j 馆藏书目约束与演示数据补全（与 Action 使用的 :LibraryBook 一致）。
需在 backend 目录下执行：  python scripts/seed_library_graph.py
或设定 PYTHONPATH 包含 backend。
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    try:
        from kg_module.env_bootstrap import load_repo_dotenv

        load_repo_dotenv()
    except Exception:
        pass
    from actions.neo4j_library_store import ensure_bootstrap  # noqa: E402

    if not ensure_bootstrap():
        print("失败：无法连接或未配置 Neo4j（请参考根目录 .env.example 填写 NEO4J_*）。")
        return 1
    print("Neo4j 馆藏演示数据就绪（constraints + LibraryBook 种子 / 补齐）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
