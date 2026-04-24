"""从 `backend/.env` 或仓库根目录 `.env` 加载变量（不覆盖已在环境中的键）。"""
from __future__ import annotations

import os
from pathlib import Path


def load_repo_dotenv() -> None:
    kg = Path(__file__).resolve().parent
    for root in (kg.parent, kg.parent.parent):
        envp = root / ".env"
        if not envp.is_file():
            continue
        for line in envp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if not val:
                continue
            os.environ[key] = val
        return
