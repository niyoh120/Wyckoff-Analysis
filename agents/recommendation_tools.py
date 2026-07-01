"""Agent-facing recommendation evaluation tools."""

from __future__ import annotations

import logging
import re
from typing import Any

from agents.tool_context import ToolContext

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = (1, 3, 5)
_MAX_TOP_K = 20


def evaluate_recommendation_events(
    market: str = "cn",
    horizon_days: int = 5,
    target_pct: float = 10.0,
    max_dates: int = 30,
    kline_count: int = 160,
    top_k: list[int] | str | int | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Evaluate recent recommendation rows and return the current policy picks."""

    _ = tool_context
    try:
        from workflows.recommendation_event_eval import RecommendationEventEvalRequest, build_recommendation_event_eval
        from workflows.recommendation_event_eval_summary import recommendation_event_eval_result_summary

        request = RecommendationEventEvalRequest(
            market=str(market or "cn").strip() or "cn",
            horizon_days=max(int(horizon_days), 1),
            target_pct=max(float(target_pct), 0.1),
            max_dates=max(int(max_dates), 1),
            kline_count=max(int(kline_count), 1),
            top_k=_normalize_top_k(top_k),
        )
        result = build_recommendation_event_eval(request)
        return {
            "ok": True,
            "job_kind": "recommendation_event_eval",
            "result_summary": recommendation_event_eval_result_summary(result),
            "metadata": result["metadata"],
            "summary": result["summary"],
            "policy_selection": result.get("policy_selection", {}),
            "daily": result["daily"],
        }
    except Exception as exc:
        logger.exception("evaluate_recommendation_events error")
        return {
            "error": str(exc),
            "hint": "需要 SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 和 TICKFLOW_API_KEY 可用，且推荐追踪表存在近期记录。",
        }


def _normalize_top_k(raw: list[int] | str | int | None) -> tuple[int, ...]:
    if raw in (None, ""):
        return _DEFAULT_TOP_K
    values = _top_k_values(raw)
    normalized = sorted({min(max(int(value), 1), _MAX_TOP_K) for value in values})
    return tuple(normalized) or _DEFAULT_TOP_K


def _top_k_values(raw: list[int] | str | int) -> list[int]:
    if isinstance(raw, str):
        return [int(item) for item in re.split(r"[,\s]+", raw.strip()) if item]
    if isinstance(raw, (list, tuple)):
        return [int(item) for item in raw]
    return [int(raw)]
