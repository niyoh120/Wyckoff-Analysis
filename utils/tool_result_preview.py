"""Shared tool-result serialization and compact previews."""

from __future__ import annotations

import json
import math
from typing import Any

PREVIEW_CHARS = 2_000


def serialize_tool_result(result: Any) -> str:
    """Serialize a tool result exactly once for message context."""

    return json.dumps(_json_safe(result), ensure_ascii=False, default=str, allow_nan=False)


def tool_result_preview(tool_name: str, result: Any, content: str = "") -> str:
    if tool_name == "screen_stocks" and isinstance(result, dict):
        preview = _screen_stocks_preview(result)
        if preview:
            return preview[:PREVIEW_CHARS]
    if tool_name == "generate_ai_report" and isinstance(result, dict):
        preview = _ai_report_preview(result)
        if preview:
            return preview[:PREVIEW_CHARS]
    if tool_name == "generate_strategy_decision" and isinstance(result, dict):
        preview = _strategy_decision_preview(result)
        if preview:
            return preview[:PREVIEW_CHARS]
    return content[:PREVIEW_CHARS]


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            return str(value)
    return value


def _strategy_decision_preview(result: dict[str, Any]) -> str:
    payload = _drop_empty_preview_fields(
        {
            "ok": result.get("ok"),
            "status": result.get("status"),
            "reason": result.get("reason"),
            "report_source": result.get("report_source"),
            "candidate_count": result.get("candidate_count"),
            "reviewed_codes": _preview_list(result.get("reviewed_codes"), 12),
            "reviewed_symbols": _candidate_preview_list(result.get("reviewed_symbols"), 12),
            "screen_summary": result.get("screen_summary"),
            "decision_brief": _screen_decision_preview(result.get("decision_brief")),
            "next_action": result.get("next_action"),
            "message": result.get("message"),
            "report_preview": _text_excerpt(result.get("report_preview"), 1000),
        }
    )
    return serialize_tool_result(payload) if payload else ""


def _ai_report_preview(result: dict[str, Any]) -> str:
    payload = _drop_empty_preview_fields(
        {
            "ok": result.get("ok"),
            "reason": result.get("reason"),
            "model": result.get("model"),
            "stock_count": result.get("stock_count"),
            "reviewed_codes": _preview_list(result.get("reviewed_codes"), 12),
            "reviewed_symbols": _candidate_preview_list(result.get("reviewed_symbols"), 12),
            "next_action": result.get("next_action"),
            "next_tool": result.get("next_tool"),
            "report_excerpt": _text_excerpt(result.get("report_text"), 1400),
        }
    )
    return serialize_tool_result(payload) if payload else ""


def _screen_stocks_preview(result: dict[str, Any]) -> str:
    payload = _drop_empty_preview_fields(
        {
            "ok": result.get("ok"),
            "board": result.get("board"),
            "summary": result.get("summary"),
            "trade_mode": result.get("trade_mode"),
            "decision_brief": _screen_decision_preview(result.get("decision_brief")),
            "selection_brief": _screen_selection_preview(result.get("selection_brief")),
            "top_candidates": _candidate_preview_list(result.get("top_candidates"), 10),
            "symbols_for_report": _candidate_preview_list(result.get("symbols_for_report"), 12),
            "action_plan": _screen_action_plan_preview(result.get("action_plan")),
            "top_sectors": _preview_list(result.get("top_sectors"), 6),
            "omitted": "完整 trigger_groups 已保留在完整结果中" if result.get("trigger_groups") else "",
        }
    )
    return serialize_tool_result(payload) if payload else ""


def _screen_decision_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "market_gate": value.get("market_gate"),
            "next_action": value.get("next_action"),
            "report_focus": _candidate_preview_list(value.get("report_focus"), 6),
            "watch_focus": _candidate_preview_list(value.get("watch_focus"), 6),
        }
    )


def _screen_selection_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "status": value.get("status"),
            "headline": value.get("headline"),
            "best_codes": _preview_list(value.get("best_codes"), 12),
            "primary_pick": _candidate_preview_item(value.get("primary_pick")),
            "best_candidates": _candidate_preview_list(value.get("best_candidates"), 6),
            "tool_handoff": value.get("tool_handoff"),
        }
    )


def _screen_action_plan_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "primary_action": value.get("primary_action"),
            "candidate_action": value.get("candidate_action"),
            "new_buy_allowed": value.get("new_buy_allowed"),
            "review_targets": value.get("review_targets"),
            "report_candidates": _candidate_preview_list(value.get("report_candidates"), 6),
            "watch_candidates": _candidate_preview_list(value.get("watch_candidates"), 6),
        }
    )


_CANDIDATE_PREVIEW_FIELDS = (
    "code",
    "name",
    "summary",
    "tier",
    "quality",
    "track",
    "stage",
    "candidate_lane",
    "entry_type",
    "selection_source",
    "priority_rank",
    "priority_score",
    "score",
    "rank_reason",
    "quality_factors",
    "risk_factors",
    "action_status",
    "why",
    "evidence",
    "next_step",
    "triggers",
)


def _candidate_preview_list(value: Any, limit: int) -> list[Any]:
    rows = _preview_list(value, limit)
    return [_candidate_preview_item(row) if isinstance(row, dict) else row for row in rows]


def _candidate_preview_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {field: _candidate_preview_value(field, value.get(field)) for field in _CANDIDATE_PREVIEW_FIELDS}
    )


def _candidate_preview_value(field: str, value: Any) -> Any:
    if isinstance(value, list):
        return [_text_excerpt(item, 80) for item in value[:8] if str(item).strip()]
    if field in {"summary", "rank_reason", "why", "evidence", "next_step"}:
        return _text_excerpt(value, 240)
    return value


def _preview_list(value: Any, limit: int) -> list[Any]:
    return list(value[:limit]) if isinstance(value, list) else []


def _text_excerpt(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _drop_empty_preview_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != "" and value != [] and value != {}
    }
