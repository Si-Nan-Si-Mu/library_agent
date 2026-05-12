"""推荐阅读：轻量「联网参考」摘要（无 API Key 时优先 Wikipedia 开放检索，失败则降级为空）。"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import List

logger = logging.getLogger(__name__)

_WIKI_LANG = (os.environ.get("READING_WEB_WIKI_LANG") or "zh").strip() or "zh"
_TIMEOUT = float(os.environ.get("READING_WEB_TIMEOUT") or "8")


def _http_get_json(url: str, timeout: float):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "library_agent/1.0 (reading recommend; educational demo)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception as exc:  # pragma: no cover - 网络/解析
        logger.debug("reading_web_search GET %s: %s", url[:120], exc)
        return None


def _wikipedia_opensearch_lines(topic: str, *, limit: int = 5) -> List[str]:
    q = (topic or "").strip()
    if not q or len(q) > 80:
        return []
    host = f"{_WIKI_LANG}.wikipedia.org"
    qs = urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": q,
            "limit": str(limit),
            "namespace": "0",
            "format": "json",
        }
    )
    url = f"https://{host}/w/api.php?{qs}"
    data = _http_get_json(url, _TIMEOUT)
    if not isinstance(data, list) or len(data) < 4:
        return []
    titles = data[1] if isinstance(data[1], list) else []
    descs = data[2] if isinstance(data[2], list) else []
    out: List[str] = []
    for i, title in enumerate(titles):
        if not isinstance(title, str) or not title.strip():
            continue
        d = descs[i] if i < len(descs) and isinstance(descs[i], str) else ""
        d = re.sub(r"\s+", " ", d).strip()
        if d:
            out.append(f"- {title}：{d[:220]}{'…' if len(d) > 220 else ''}")
        else:
            out.append(f"- {title}")
        if len(out) >= limit:
            break
    return out


def _duckduckgo_related(topic: str, *, limit: int = 4) -> List[str]:
    q = (topic or "").strip()
    if not q or len(q) > 100:
        return []
    qs = urllib.parse.urlencode({"q": f"{q} 图书 推荐", "format": "json", "no_html": "1", "no_redirect": "1"})
    url = f"https://api.duckduckgo.com/?{qs}"
    data = _http_get_json(url, min(_TIMEOUT, 6.0))
    if not isinstance(data, dict):
        return []
    lines: List[str] = []
    abst = (data.get("AbstractText") or "").strip()
    if abst:
        lines.append(f"- 摘要：{abst[:320]}{'…' if len(abst) > 320 else ''}")
    rel = data.get("RelatedTopics") or []
    if isinstance(rel, list):
        for item in rel:
            if len(lines) >= limit:
                break
            if isinstance(item, dict):
                t = (item.get("Text") or "").strip()
                if t:
                    lines.append(f"- {t[:240]}{'…' if len(t) > 240 else ''}")
            elif isinstance(item, str) and item.strip():
                lines.append(f"- {item.strip()[:240]}")
    return lines[:limit]


def build_reading_web_context(topic: str) -> str:
    """
    供 DeepSeek 参考的短文本（非馆内事实）。可能为空。
    可用环境变量 READING_WEB_DISABLED=1 关闭联网请求。
    """
    if (os.environ.get("READING_WEB_DISABLED") or "").strip() in ("1", "true", "yes", "on"):
        return ""
    topic = (topic or "").strip()
    if not topic:
        return ""

    parts: List[str] = []
    wiki = _wikipedia_opensearch_lines(topic, limit=5)
    if wiki:
        parts.append("【维基百科开放检索条目摘要（仅供参考，非本馆书目）】\n" + "\n".join(wiki))
    if len("\n".join(parts)) < 400:
        ddg = _duckduckgo_related(topic, limit=3)
        if ddg:
            parts.append("【网络检索摘要片段（仅供参考）】\n" + "\n".join(ddg))
    return "\n\n".join(parts).strip()
