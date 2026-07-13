"""Low-sensitivity disagreement summary for dynamic workflow synthesis."""

from __future__ import annotations

from typing import Any

_BULLISH_MARKERS = ("强烈看多", "看多", "买入", "加仓", "做多", "偏多", "进攻")
_BEARISH_MARKERS = ("不建议买入", "不宜买入", "卖出", "减仓", "看空", "避险", "防御", "止损", "离场")
_NEUTRAL_MARKERS = ("观望", "持有", "等待", "中性", "不操作", "暂不")
_RESULT_LIMIT = 400


def build_workflow_disagreement_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize directional agreement without carrying raw agent reasoning."""
    buckets: dict[str, list[dict[str, str]]] = {
        "bullish_agents": [],
        "bearish_agents": [],
        "neutral_agents": [],
    }
    degraded_steps: list[dict[str, str]] = []

    for item in results:
        if not isinstance(item, dict):
            continue
        step = item.get("step") if isinstance(item.get("step"), dict) else {}
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        agent = str(result.get("agent") or step.get("agent") or "task").strip() or "task"
        title = str(step.get("title") or step.get("step_id") or agent).strip() or agent
        status = str(result.get("status") or "unknown").strip().lower()
        if status != "completed":
            degraded_steps.append({"agent": agent, "step": title, "status": status})
            continue
        signal = _classify_signal(result.get("result"))
        buckets[f"{signal}_agents"].append({"agent": agent, "step": title, "signal": signal})

    conflict_type = _conflict_type(buckets, degraded_steps)
    return {
        **buckets,
        "conflict_type": conflict_type,
        "decision_path_hint": _decision_path_hint(conflict_type),
        "degraded_steps": degraded_steps[:8],
    }


def _classify_signal(value: Any) -> str:
    text = str(value or "").lower()[:_RESULT_LIMIT]
    if any(marker in text for marker in _BEARISH_MARKERS):
        return "bearish"
    if any(marker in text for marker in _BULLISH_MARKERS):
        return "bullish"
    if any(marker in text for marker in _NEUTRAL_MARKERS):
        return "neutral"
    return "neutral"


def _conflict_type(buckets: dict[str, list[dict[str, str]]], degraded_steps: list[dict[str, str]]) -> str:
    bullish = buckets["bullish_agents"]
    bearish = buckets["bearish_agents"]
    neutral = buckets["neutral_agents"]
    if bullish and bearish:
        return "mixed_directional_signals"
    if degraded_steps:
        if bullish:
            return "partial_bullish_with_degraded_inputs"
        if bearish:
            return "partial_bearish_with_degraded_inputs"
        return "degraded_inputs"
    if bullish:
        return "bullish_with_neutral" if neutral else "aligned_bullish"
    if bearish:
        return "bearish_with_neutral" if neutral else "aligned_bearish"
    return "aligned_neutral"


def _decision_path_hint(conflict_type: str) -> str:
    return {
        "mixed_directional_signals": "explain_cross_agent_conflict_before_any_action",
        "partial_bullish_with_degraded_inputs": "state_data_limitations_and_require_confirmation_before_bullish_action",
        "partial_bearish_with_degraded_inputs": "state_data_limitations_and_preserve_downside_controls",
        "degraded_inputs": "state_data_limitations_before_recommendation",
        "aligned_bullish": "require_price_and_risk_confirmation_before_action",
        "bullish_with_neutral": "lean_bullish_but_require_confirmation",
        "aligned_bearish": "preserve_downside_controls",
        "bearish_with_neutral": "lean_defensive_and_require_recovery_confirmation",
        "aligned_neutral": "prefer_watchlist_or_hold_plan",
    }[conflict_type]


__all__ = ["build_workflow_disagreement_summary"]
