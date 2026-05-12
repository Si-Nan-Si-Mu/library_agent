"""调用 DeepSeek OpenAI 兼容接口（/v1/chat/completions），供 Action Server 使用。"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import requests

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def deepseek_chat(
    user_message: str,
    *,
    system: Optional[str] = None,
    timeout: float = 60.0,
    temperature: Optional[float] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    返回 (assistant_text, error_code)。
    error_code 为 None 表示成功；否则为简短机器可读原因。
    """
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        return None, "missing_api_key"

    base = (os.environ.get("DEEPSEEK_API_BASE") or DEFAULT_BASE).rstrip("/")
    model = (os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    url = f"{base}/v1/chat/completions"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_message})

    temp = (
        temperature
        if temperature is not None
        else float(os.environ.get("DEEPSEEK_TEMPERATURE") or "0.6")
    )
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temp,
        "max_tokens": int(os.environ.get("DEEPSEEK_MAX_TOKENS") or "1024"),
    }

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return None, f"request_error:{type(exc).__name__}"

    if resp.status_code != 200:
        return None, f"http_{resp.status_code}"

    try:
        data = resp.json()
        choice0 = (data.get("choices") or [{}])[0]
        msg = choice0.get("message") or {}
        content = (msg.get("content") or "").strip()
    except (TypeError, ValueError, KeyError, IndexError):
        return None, "parse_error"

    if not content:
        return None, "empty_content"
    return content, None
