"""Shared risk-adjusted candidate quality helpers."""

from __future__ import annotations

from typing import Any

from core.candidate_policy import candidate_score_value

ENTRY_RISK_FLAG_PENALTY = 5.0
MAX_ENTRY_RISK_FLAG_PENALTY = 20.0


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
