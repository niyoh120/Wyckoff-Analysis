"""Shared risk-adjusted candidate quality helpers."""

from __future__ import annotations

from typing import Any

from core.candidate_policy import candidate_score_value

ENTRY_RISK_FLAG_PENALTY = 5.0
MAX_ENTRY_RISK_FLAG_PENALTY = 20.0
MIN_AI_REVIEW_RISK_ADJUSTED_QUALITY = 70.0


def entry_quality_risk_flags(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def candidate_raw_quality_score(row: dict[str, Any]) -> float:
    return max(
        candidate_score_value(row.get("funnel_score")),
        candidate_score_value(row.get("candidate_shadow_score")),
        candidate_score_value(row.get("entry_quality_score")),
    )


def risk_adjusted_quality_score(row: dict[str, Any]) -> float:
    return max(0.0, candidate_raw_quality_score(row) - entry_quality_risk_penalty(row))


def entry_quality_risk_penalty(row: dict[str, Any]) -> float:
    count = len(entry_quality_risk_flags(row.get("entry_quality_risk_flags")))
    return min(MAX_ENTRY_RISK_FLAG_PENALTY, count * ENTRY_RISK_FLAG_PENALTY)


def risk_adjusted_quality_metrics(row: dict[str, Any]) -> dict[str, float]:
    raw_score = candidate_raw_quality_score(row)
    risk_penalty = entry_quality_risk_penalty(row)
    payload: dict[str, float] = {}
    if raw_score:
        payload["candidate_quality_score"] = round(raw_score, 2)
        payload["risk_adjusted_quality_score"] = round(risk_adjusted_quality_score(row), 2)
    if risk_penalty:
        payload["entry_risk_penalty"] = round(risk_penalty, 2)
    return payload


def ai_review_quality_gate_reason(row: dict[str, Any], label: str = "候选") -> str:
    if not _has_explicit_quality_score(row):
        return ""
    score = risk_adjusted_quality_score(row)
    if score >= MIN_AI_REVIEW_RISK_ADJUSTED_QUALITY:
        return ""
    return f"{label} 风险调整质量分 {score:.2f} 低于AI复核门槛 {MIN_AI_REVIEW_RISK_ADJUSTED_QUALITY:.2f}"


def candidate_ai_review_label(row: dict[str, Any]) -> str:
    code = str(row.get("code") or row.get("symbol") or "").strip()
    name = str(row.get("name") or "").strip()
    return " ".join(part for part in (code, name) if part) or "候选"


def split_ai_review_candidates(
    rows: list[Any],
    *,
    selected_required: bool = True,
    selected_key: str = "selected_for_report",
) -> dict[str, Any]:
    report_candidates: list[Any] = []
    watch_candidates: list[Any] = []
    blocked: list[dict[str, Any]] = []
    for row in rows:
        row_payload = _candidate_row_payload(row)
        if selected_required and not bool(row_payload.get(selected_key)):
            watch_candidates.append(row)
            continue
        reason = ai_review_quality_gate_reason(row_payload, candidate_ai_review_label(row_payload))
        if reason:
            watch_candidates.append(row)
            blocked.append(_blocked_candidate(row_payload, reason))
            continue
        report_candidates.append(row)
    payload: dict[str, Any] = {"report_candidates": report_candidates, "watch_candidates": watch_candidates}
    if blocked:
        payload["quality_gate"] = {
            "status": "blocked_by_quality_gate",
            "reason": blocked[0]["reason"],
            "blocked_count": len(blocked),
            "candidates": blocked[:5],
        }
    return payload


def _candidate_row_payload(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    return {"code": str(row or "").strip()}


def _blocked_candidate(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"code": row.get("code") or row.get("symbol"), "name": row.get("name"), "reason": reason}


def _has_explicit_quality_score(row: dict[str, Any]) -> bool:
    return row.get("candidate_shadow_score") not in (None, "", []) or row.get("entry_quality_score") not in (
        None,
        "",
        [],
    )
