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
            "reviewed_symbols": _preview_list(result.get("reviewed_symbols"), 12),
            "screen_summary": result.get("screen_summary"),
            "decision_brief": result.get("decision_brief"),
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
            "reviewed_symbols": _preview_list(result.get("reviewed_symbols"), 12),
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
            "decision_brief": result.get("decision_brief"),
            "selection_brief": result.get("selection_brief"),
            "action_plan": result.get("action_plan"),
            "top_candidates": _preview_list(result.get("top_candidates"), 10),
            "symbols_for_report": _preview_list(result.get("symbols_for_report"), 12),
            "top_sectors": _preview_list(result.get("top_sectors"), 6),
            "omitted": "完整 trigger_groups 已保留在完整结果中" if result.get("trigger_groups") else "",
        }
    )
    return serialize_tool_result(payload) if payload else ""


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
