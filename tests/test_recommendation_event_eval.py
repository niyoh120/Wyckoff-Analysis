from __future__ import annotations

import pytest

from workflows.recommendation_event_eval import (
    RecommendationEventEvalRequest,
    _label_update_row,
    _top_k_summary,
    _validate_persistence_target,
)


def test_top_k_summary_ranks_ai_then_score_then_count() -> None:
    events = [
        _event(20260515, "A", ai=False, score=0.99, count=3, hit=True),
        _event(20260515, "B", ai=True, score=0.30, count=1, hit=True),
        _event(20260515, "C", ai=False, score=0.80, count=1, hit=False),
        _event(20260516, "D", ai=False, score=0.70, count=2, hit=False),
        _event(20260516, "E", ai=False, score=0.90, count=1, hit=True),
    ]

    top1 = _top_k_summary(events, 1)
    top2_score = _top_k_summary(events, 2)
    top2_ai = _top_k_summary(events, 2, "ai_then_score")

    assert top1["rows_total"] == 2
    assert top1["hit_count"] == 2
    assert top1["hit_rate_pct"] == 100.0
    assert top2_score["rows_total"] == 4
    assert top2_score["hit_count"] == 2
    assert top2_score["hit_rate_pct"] == 50.0
    assert top2_ai["hit_count"] == 3
    assert top2_ai["hit_rate_pct"] == 75.0
    assert top2_ai["days_covered"] == 2


def test_label_update_row_keeps_partial_non_hit_unknown() -> None:
    row = _label_update_row(
        {
            "id": "row1",
            "label_ready": False,
            "hit_target": False,
            "mfe_horizon_pct": 8.0,
            "mae_horizon_pct": -3.0,
        },
        "now",
    )

    assert row is not None
    assert row["label_5d_ready"] is False
    assert row["hit_10_5d"] is None
    assert row["mfe_5d_pct"] is None
    assert row["mae_5d_pct"] is None


def test_label_update_row_can_mark_partial_already_hit() -> None:
    row = _label_update_row(
        {
            "id": "row1",
            "label_ready": False,
            "hit_target": True,
            "first_hit_date": 20260626,
            "days_to_hit": 2,
        },
        "now",
    )

    assert row is not None
    assert row["label_5d_ready"] is False
    assert row["hit_10_5d"] is True
    assert row["first_hit_10_5d_date"] == 20260626
    assert row["days_to_hit_10_5d"] == 2


def test_validate_persistence_target_only_allows_5d_10pct() -> None:
    _validate_persistence_target(RecommendationEventEvalRequest(horizon_days=5, target_pct=10.0))
    with pytest.raises(ValueError, match="horizon_days=5"):
        _validate_persistence_target(RecommendationEventEvalRequest(horizon_days=10, target_pct=10.0))


def _event(
    rec_date: int,
    code: str,
    *,
    ai: bool,
    score: float,
    count: int,
    hit: bool,
) -> dict:
    return {
        "recommend_date": rec_date,
        "code": code,
        "is_ai_recommended": ai,
        "funnel_score": score,
        "recommend_count": count,
        "label_ready": True,
        "hit_target": hit,
        "mfe_horizon_pct": 12.0 if hit else 4.0,
        "mae_horizon_pct": -3.0,
    }
