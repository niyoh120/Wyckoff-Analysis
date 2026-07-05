"""Shared strategy governance context helpers for agent handoffs."""

from __future__ import annotations

from typing import Any

from utils.safe import has_value as _has_value


def report_with_strategy_policy_context(report_text: str, screen_result: dict | None) -> str:
    lines = strategy_policy_context_lines(screen_strategy_policy(screen_result))
    text = str(report_text or "").strip()
    if not lines or "## 策略治理上下文" in text:
        return text
    context = "## 策略治理上下文\n" + "\n".join(f"- {line}" for line in lines)
    return f"{context}\n\n{text}" if text else context


def strategy_policy_context_lines(policy: dict[str, Any]) -> list[str]:
    if not policy:
        return []
    lines: list[str] = []
    _append_policy_line(lines, "执行模式", policy.get("execution_policy"))
    _append_policy_line(lines, "动态模式", policy.get("dynamic_mode"))
    _append_policy_line(lines, "作用范围", policy.get("policy_weight_active_scope"))
    _append_policy_line(lines, "候选源治理", policy.get("selection_action_summary"))
    _append_policy_line(lines, "下一步", policy.get("next_action"))
    weights = policy.get("attribution_signal_weights") or policy.get("signal_weights")
    if isinstance(weights, dict) and weights:
        lines.append("信号调权: " + ", ".join(f"{key}={value}" for key, value in weights.items()))
    return lines


def screen_strategy_policy(screen_result: dict | None) -> dict[str, Any]:
    if not isinstance(screen_result, dict):
        return {}
    value = screen_result.get("strategy_policy")
    return dict(value) if isinstance(value, dict) and value else {}


def _append_policy_line(lines: list[str], label: str, value: Any) -> None:
    if _has_value(value):
        lines.append(f"{label}: {value}")
