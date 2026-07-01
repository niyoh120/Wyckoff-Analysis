"""Shared candidate guard summaries for selection handoffs."""

from __future__ import annotations

from typing import Any

BLOCKING_CANDIDATE_ACTION_STATUSES = {
    "watch_only",
    "blocked_by_data_quality",
    "blocked_by_market_gate",
    "blocked_by_policy_guard",
    "repair_review_only",
    "confirmation_required",
}


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
    return candidate_guard_summary([row for row in picks if isinstance(row, dict)])


def candidate_guard_item(row: dict[str, Any]) -> dict[str, Any]:
    reason = candidate_guard_reason(row)
    if not reason:
        return {}
    return _compact_guard_item(
        {
            "code": row.get("code"),
            "name": row.get("name"),
            "reason": reason,
            "action_status": row.get("action_status"),
            "label_ready": row.get("label_ready"),
            "risk_factors": _candidate_guard_risks(row),
            "next_step": row.get("next_step"),
        }
    )


def candidate_guard_reason(row: dict[str, Any]) -> str:
    if row.get("label_ready") is False:
        return "候选标签未成熟，禁止直接买入"
    status = str(row.get("action_status") or "").strip()
    if status.startswith("blocked_") or status in BLOCKING_CANDIDATE_ACTION_STATUSES:
        return f"候选状态 {status} 不允许直接买入"
    return ""


def _candidate_guard_risks(row: dict[str, Any]) -> list[str]:
    risks = row.get("risk_factors")
    if not isinstance(risks, list):
        return []
    return [str(item).strip() for item in risks[:3] if str(item).strip()]


def _compact_guard_item(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value not in (None, "", [], {})}
