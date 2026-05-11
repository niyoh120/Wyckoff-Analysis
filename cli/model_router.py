"""LLM 任务路由 — 按消息复杂度自动选择 heavy/light 模型。"""

from __future__ import annotations

import re
from collections.abc import Generator
from typing import Any

from cli.providers.base import LLMProvider

_HEAVY_KEYWORDS = re.compile(
    r"分析|诊断|策略|研报|决策|回测|漏斗|筛选|持仓|复盘|"
    r"analyze|diagnose|strategy|backtest|screen|funnel|portfolio"
)


def classify_turn(messages: list[dict[str, Any]]) -> str:
    """根据最后一轮消息判断应使用 heavy 还是 light 模型。"""
    if not messages:
        return "heavy"

    last_user = None
    tool_result_count = 0
    for msg in reversed(messages):
        role = msg.get("role", "")
        if role == "user" and last_user is None:
            last_user = msg
        if role == "tool":
            tool_result_count += 1

    if tool_result_count >= 2:
        return "heavy"

    if last_user is None:
        return "heavy"

    parts = last_user.get("parts", [])
    text = ""
    if isinstance(parts, list):
        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text:
        text = last_user.get("content", "")
    if isinstance(text, list):
        text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))

    if _HEAVY_KEYWORDS.search(text):
        return "heavy"

    if len(text) > 80:
        return "heavy"

    return "light"


class RoutingProvider(LLMProvider):
    """包装 heavy + light 两个 provider，每次调用前按消息分类选择。"""

    def __init__(self, heavy: LLMProvider, light: LLMProvider):
        self._heavy = heavy
        self._light = light
        self._active: LLMProvider = heavy
        self.last_tier: str = "heavy"

    @property
    def name(self) -> str:
        return self._active.name

    @property
    def tier_label(self) -> str:
        return f"{'⚡' if self.last_tier == 'light' else '🧠'} {self._active.name}"

    def _select(self, messages: list[dict[str, Any]]) -> LLMProvider:
        self.last_tier = classify_turn(messages)
        self._active = self._light if self.last_tier == "light" else self._heavy
        return self._active

    def chat(self, messages, tools, system_prompt=""):
        provider = self._select(messages)
        return provider.chat(messages, tools, system_prompt)

    def chat_stream(self, messages, tools, system_prompt=""):
        provider = self._select(messages)
        yield from provider.chat_stream(messages, tools, system_prompt)
