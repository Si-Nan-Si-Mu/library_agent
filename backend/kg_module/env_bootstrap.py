"""从仓库根目录与 `backend/.env` 加载变量（后者覆盖前者）；不覆盖已在 os.environ 中的键（便于系统/CI 注入）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def _parse_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if not val:
            continue
        out[key] = val
    return out


def load_repo_dotenv() -> None:
    """
    合并加载：先 `library_agent/.env`，再 `backend/.env`（同名键以后者为准）。
    若某键已在 os.environ 中（例如 Windows 用户环境变量、Conda activate 脚本），则保持不动。
    """
    kg = Path(__file__).resolve().parent
    backend_dir = kg.parent
    repo_root = kg.parent.parent

    merged: Dict[str, str] = {}
    for env_dir in (repo_root, backend_dir):
        merged.update(_parse_env_file(env_dir / ".env"))

    for key, val in merged.items():
        if key in os.environ:
            continue
        os.environ[key] = val
