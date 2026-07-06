"""Shared candidate guard summaries for selection handoffs."""

from __future__ import annotations

from typing import Any

from core.candidate_actions import (
    _is_false,
    candidate_action_blocks_direct_buy,
    candidate_action_fields,
)


def candidate_guard_summary(candidate_meta: list[dict]) -> dict[str, Any]:
    blocked = [candidate_guard_item(row) for row in candidate_meta if isinstance(row, dict)]
    blocked = [row for row in blocked if row]
    if not blocked:
        return {}
    return {
        "direct_buy_blocked_count": len(blocked),
        "message": "以下候选仅可复核或观察，禁止直接买入",
        "candidates": blocked[:5],
    }


def policy_candidate_guard_summary(selection: Any, result: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("candidate_guard_summary"), dict):
        return result["candidate_guard_summary"]
    if not isinstance(selection, dict):
        return {}
    picks = selection.get("picks")
    if not isinstance(picks, list):
        return {}
    return candidate_guard_summary(_policy_guard_rows(selection, picks))


def _policy_guard_rows(selection: dict[str, Any], picks: list[Any]) -> list[dict]:
    action_plan = selection.get("action_plan") if isinstance(selection.get("action_plan"), dict) else {}
    return [_policy_guard_row(row, action_plan) for row in picks if isinstance(row, dict)]


def _policy_guard_row(row: dict[str, Any], action_plan: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    for field in ("trade_readiness", "new_buy_allowed", "ai_review_allowed"):
        if field not in payload and field in action_plan:
            payload[field] = action_plan[field]
    return payload


def candidate_guard_item(row: dict[str, Any]) -> dict[str, Any]:
    reason = candidate_guard_reason(row)
    if not reason:
        return {}
    action_fields = candidate_action_fields(row)
    return _compact_guard_item(
        {
            "code": row.get("code"),
            "name": row.get("name"),
            "reason": reason,
            **action_fields,
            "label_ready": row.get("label_ready"),
            "trade_readiness": row.get("trade_readiness"),
            "new_buy_allowed": row.get("new_buy_allowed"),
            "risk_factors": _candidate_guard_risks(row),
            "next_step": row.get("next_step"),
        }
    )


def candidate_guard_reason(row: dict[str, Any]) -> str:
    if row.get("label_ready") is False:
        return "候选标签未成熟，禁止直接买入"
    if _is_false(row.get("new_buy_allowed")):
        return "候选未开放新增买入，禁止直接买入"
    trade_readiness = str(row.get("trade_readiness") or "").strip()
    if trade_readiness in {"research_only", "review_only"}:
        return f"候选交易就绪状态 {trade_readiness} 不允许直接买入"
    status = str(row.get("action_status") or "").strip()
    if status and candidate_action_blocks_direct_buy(status):
        return f"候选状态 {status} 不允许直接买入"
    return ""


def _candidate_guard_risks(row: dict[str, Any]) -> list[str]:
    risks = row.get("risk_factors")
    if not isinstance(risks, list):
        return []
    return [str(item).strip() for item in risks[:3] if str(item).strip()]


def _compact_guard_item(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in (None, "", [], {})}
