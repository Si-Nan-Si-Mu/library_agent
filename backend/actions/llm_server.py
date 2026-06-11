"""
LLM Prompt 组装与调用层（构成对齐 library-RAG-Rasa 仓库的 actions/llm_server.py）。

与参考仓库的差异：
- 默认走本地已配置的 DeepSeek（deepseek_client.deepseek_chat，.env 中 DEEPSEEK_API_KEY）；
- 若 .env 配置 OLLAMA_URL（如 http://localhost:11434），优先尝试本地 Ollama（OLLAMA_MODEL，默认 qwen2.5:7b）；
- 两者均不可用时回退为结构化数据文本（与仓库兜底行为一致）。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import requests

from .deepseek_client import deepseek_chat

logger = logging.getLogger(__name__)


def _ollama_generate(prompt: str) -> Optional[str]:
    base = (os.environ.get("OLLAMA_URL") or "").strip().rstrip("/")
    if not base:
        return None
    model = (os.environ.get("OLLAMA_MODEL") or "qwen2.5:7b").strip()
    try:
        resp = requests.post(
            f"{base}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        text = (resp.json().get("response") or "").strip()
        return text or None
    except Exception as exc:
        logger.info("Ollama 请求失败，回退 DeepSeek/结构化: %s", exc)
        return None


def _generate(prompt: str) -> Optional[str]:
    """优先 Ollama（若配置），否则 DeepSeek；都失败返回 None。"""
    text = _ollama_generate(prompt)
    if text:
        return text
    reply, err = deepseek_chat(prompt, timeout=50.0, temperature=0.5)
    if reply and not err:
        return reply
    if err and err != "missing_api_key":
        logger.info("DeepSeek 生成失败: %s", err)
    return None


def generate_llm_reply(topic: str, kg_context: Any) -> str:
    """主题荐书的自然语言生成（对齐仓库 generate_ollama_reply 的 Prompt 约束）。"""
    prompt = f"""
    你是一个专业的图书馆智能助理。用户正在寻找关于【{topic}】方向的书籍。
    我从图书馆知识图谱中为你检索到了以下真实的书籍资料：
    {json.dumps(kg_context, ensure_ascii=False, indent=2)}

    请根据以上资料，用自然、专业且友好的语气向用户推荐。
    要求：
    1. 必须基于提供的资料进行推荐，绝对不能虚构或编造图谱中没有的书籍。
    2. 顺便提一下书籍的作者、评分和亮点简介；在架状态以资料为准。
    3. 排版清晰，可以直接给用户阅读；不要使用表情符号。
    4. 重点：如果资料中体现了书籍之间的关联（如同一作者、同一学科等），请以「推荐理由」或「相关性」的形式巧妙融入回答，展现知识图谱的深度。
    """
    text = _generate(prompt)
    if text:
        return text
    return (
        "[系统提示：生成服务未开启，回退为结构化数据]\n为您找到以下书籍：\n"
        + json.dumps(kg_context, ensure_ascii=False, indent=2)
    )


def generate_author_reply(author_name: str, kg_context: Any) -> str:
    """作者档案介绍的自然语言生成（对齐仓库 generate_author_reply 的 Prompt 约束）。"""
    prompt = f"""
    你是一个专业的图书馆助理。用户正在询问关于作家/学者【{author_name}】的信息。
    我从知识图谱中为你提取了该作者的全方位档案（包含生平、馆藏著作以及与其他人物的关联）：

    {json.dumps(kg_context, ensure_ascii=False, indent=2)}

    请根据以上资料，为用户生成一段专业、生动的人物介绍。
    要求：
    1. 必须提及作者的主要研究/创作领域和生平亮点。
    2. 如果该作者有馆藏著作，请顺带推荐。
    3. 重点：如果资料中提到了该作者与其他人物的关联（如受谁影响、与谁同时代等），请以「学术脉络」或「趣闻」的形式巧妙融入回答，展现知识图谱的深度。
    4. 严禁编造资料中未提供的书籍或人物关系；不要使用表情符号。
    """
    text = _generate(prompt)
    if text:
        return text
    return (
        "[系统提示：生成服务未开启]\n查找到作者资料：\n"
        + json.dumps(kg_context, ensure_ascii=False, indent=2)
    )
