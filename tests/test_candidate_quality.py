from __future__ import annotations

from core.candidate_quality import (
    ai_review_quality_gate_reason,
    entry_quality_risk_flags,
    entry_quality_risk_penalty,
    risk_adjusted_quality_metrics,
)


def test_risk_adjusted_quality_metrics_penalize_entry_risks() -> None:
    row = {
        "funnel_score": 89.5,
        "candidate_shadow_score": 92.0,
        "entry_quality_score": 84.0,
        "entry_quality_risk_flags": ["短线涨幅偏快", "供给压力未消化"],
    }

    assert risk_adjusted_quality_metrics(row) == {
        "candidate_quality_score": 92.0,
        "risk_adjusted_quality_score": 82.0,
        "entry_risk_penalty": 10.0,
    }


def test_entry_quality_risk_penalty_is_capped() -> None:
    row = {"candidate_shadow_score": 90.0, "entry_quality_risk_flags": ["a", "b", "c", "d", "e"]}

    assert entry_quality_risk_penalty(row) == 20.0
    assert risk_adjusted_quality_metrics(row)["risk_adjusted_quality_score"] == 70.0


def test_entry_quality_risk_flags_accept_scalar_text() -> None:
    assert entry_quality_risk_flags(" 短线涨幅偏快 ") == ["短线涨幅偏快"]
    assert entry_quality_risk_flags("") == []


def test_ai_review_quality_gate_reason_requires_explicit_quality_score() -> None:
    assert ai_review_quality_gate_reason({"funnel_score": 0.99}, "LOW") == ""
    assert ai_review_quality_gate_reason({"candidate_shadow_score": 65.0}, "LOW") == (
        "LOW 风险调整质量分 65.00 低于AI复核门槛 70.00"
    )
    assert ai_review_quality_gate_reason({"candidate_shadow_score": 70.0}, "OK") == ""
