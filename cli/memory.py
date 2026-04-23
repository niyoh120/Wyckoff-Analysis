# -*- coding: utf-8 -*-
"""
Agent 跨会话记忆 — 会话摘要提取 + 记忆注入。
"""
from __future__ import annotations

import re
from typing import Any

_SESSION_SUMMARY_PROMPT = """请将以下对话提取为结构化记忆（中文，≤300字）：
1. 讨论了哪些股票（代码+结论）
2. 用户的操作意图和决策
3. 重要的市场判断
每条记忆一行，前缀标注类型：[股票] / [决策] / [市场]
只保留有价值的结论，忽略寒暄和工具调用细节。"""

_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def extract_stock_codes(text: str) -> list[str]:
    """从文本中提取 6 位股票代码。"""
    return list(dict.fromkeys(_CODE_RE.findall(text)))


def _has_tool_calls(messages: list[dict]) -> bool:
    return any(m.get("tool_calls") for m in messages)


def save_session_summary(messages: list[dict], provider: Any) -> None:
    """会话结束时，用 LLM 提取关键结论存入 agent_memory。"""
    if not messages or len(messages) < 4 or not _has_tool_calls(messages):
        return
    try:
        from integrations.local_db import save_memory

        # 构建对话摘要输入
        lines = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "tool":
                content = content[:200] + "..." if len(content) > 200 else content
            if content:
                lines.append(f"[{role}] {content}")
        dialog_text = "\n".join(lines[-40:])  # 最多取最近 40 条

        chunks = list(provider.chat_stream(
            [{"role": "user", "content": dialog_text}],
            [],
            _SESSION_SUMMARY_PROMPT,
        ))
        summary = "".join(c.get("text", "") for c in chunks if c.get("type") == "text_delta")
        if not summary or len(summary) < 10:
            return

        # 提取涉及的股票代码
        all_text = " ".join(m.get("content", "") or "" for m in messages)
        codes = extract_stock_codes(all_text)
        codes_str = ",".join(codes[:20])

        save_memory("session", summary.strip(), codes=codes_str)
    except Exception:
        pass  # 记忆保存失败不影响主流程


def build_memory_context(user_message: str) -> str:
    """根据用户消息检索相关记忆，返回注入 system prompt 的文本。"""
    try:
        from integrations.local_db import search_memory, get_recent_memories

        memories: list[dict] = []

        # 1. 按股票代码检索
        codes = extract_stock_codes(user_message)
        if codes:
            memories = search_memory(codes=codes, limit=5)

        # 2. 补充最近的会话摘要
        recent = get_recent_memories(memory_type="session", limit=3)
        seen_ids = {m["id"] for m in memories}
        for r in recent:
            if r["id"] not in seen_ids:
                memories.append(r)

        if not memories:
            return ""

        lines = ["", "# 历史记忆"]
        for m in memories[:8]:
            date_str = str(m.get("created_at", ""))[:10]
            content = str(m.get("content", "")).strip()
            # 每条记忆截取前 200 字
            if len(content) > 200:
                content = content[:200] + "…"
            lines.append(f"- [{date_str}] {content}")
        return "\n".join(lines)
    except Exception:
        return ""
