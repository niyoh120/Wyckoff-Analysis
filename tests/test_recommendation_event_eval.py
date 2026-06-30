from __future__ import annotations

from workflows.recommendation_event_eval import (
    _build_summary,
    _observation_feature_map,
    _quality_feature_fields,
    _top_k_summary,
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


def test_top_k_summary_can_rank_by_candidate_quality_scores() -> None:
    events = [
        _event(20260515, "A", ai=False, score=0.99, count=3, hit=False, shadow=25.0, entry=30.0),
        _event(20260515, "B", ai=False, score=0.30, count=1, hit=True, shadow=88.0, entry=82.0),
        _event(20260516, "C", ai=False, score=0.95, count=2, hit=False, shadow=32.0, entry=35.0),
        _event(20260516, "D", ai=True, score=0.20, count=1, hit=True, shadow=80.0, entry=79.0),
    ]

    score_only = _top_k_summary(events, 1, "score_only")
    shadow_quality = _top_k_summary(events, 1, "candidate_shadow_then_score")
    entry_quality = _top_k_summary(events, 1, "entry_quality_then_score")
    summary = _build_summary(events, (1,))

    assert score_only["hit_rate_pct"] == 0.0
    assert shadow_quality["hit_rate_pct"] == 100.0
    assert entry_quality["hit_rate_pct"] == 100.0
    assert "candidate_shadow_then_score" in summary["top_k_by_strategy"]
    assert "entry_quality_then_score" in summary["top_k_by_strategy"]
    assert summary["top_k_lift_vs_score_only"]["candidate_shadow_then_score"]["1"]["hit_rate_delta_pct"] == 100.0
    assert summary["top_k_lift_vs_score_only"]["candidate_shadow_then_score"]["1"]["avg_mfe_delta_pct"] == 8.0
    assert summary["top_k_lift_vs_score_only"]["entry_quality_then_score"]["1"]["hit_rate_delta_pct"] == 100.0


def test_top_k_summary_can_rank_by_quality_grade_when_score_missing() -> None:
    events = [
        {**_event(20260515, "A", ai=False, score=0.99, count=3, hit=False), "candidate_shadow_grade": "D"},
        {**_event(20260515, "B", ai=False, score=0.30, count=1, hit=True), "candidate_shadow_grade": "S"},
    ]

    shadow_quality = _top_k_summary(events, 1, "candidate_shadow_then_score")

    assert shadow_quality["hit_rate_pct"] == 100.0


def test_event_summary_groups_candidate_quality_grades() -> None:
    events = [
        {**_event(20260515, "A", ai=False, score=0.99, count=3, hit=True), "candidate_shadow_grade": "S"},
        {**_event(20260515, "B", ai=False, score=0.80, count=1, hit=False), "candidate_shadow_grade": "D"},
        {**_event(20260516, "C", ai=True, score=0.70, count=1, hit=True), "entry_quality_grade": "A"},
        {**_event(20260516, "D", ai=False, score=0.50, count=2, hit=False), "entry_quality_grade": "C"},
    ]

    summary = _build_summary(events, (1, 3))

    assert summary["candidate_shadow_grade"]["S"]["hit_rate_pct"] == 100.0
    assert summary["candidate_shadow_grade"]["D"]["hit_rate_pct"] == 0.0
    assert summary["candidate_shadow_grade"]["unknown"]["rows_total"] == 2
    assert summary["entry_quality_grade"]["A"]["hit_rate_pct"] == 100.0
    assert summary["entry_quality_grade"]["C"]["hit_rate_pct"] == 0.0


def test_quality_feature_fields_merge_observation_and_row_features() -> None:
    observed = {
        "candidate_shadow_score": {"score": 88.456, "grade": "S"},
        "entry_quality": {"score": 76, "grade": "A", "risk_flags": ["缩量不足"]},
    }
    row = {
        "features_json": (
            '{"candidate_shadow_score":{"score":42,"grade":"D"},'
            '"entry_quality":{"score":"nan","grade":"Z","risk_flags":"追高延展"}}'
        )
    }

    fields = _quality_feature_fields(row, observed)

    assert fields["candidate_shadow_score"] == 42.0
    assert fields["candidate_shadow_grade"] == "D"
    assert fields["entry_quality_score"] is None
    assert fields["entry_quality_grade"] == "unknown"
    assert fields["entry_quality_risk_flags"] == ["追高延展"]


def test_observation_feature_map_merges_same_day_features() -> None:
    rows = [
        {
            "trade_date": "2026-05-15",
            "code": 1,
            "features_json": '{"candidate_shadow_score":{"score":82,"grade":"S"}}',
        },
        {
            "trade_date": "20260515",
            "code": "000001",
            "features_json": {"entry_quality": {"score": 72, "grade": "A"}},
        },
    ]

    features = _observation_feature_map(rows)[("000001", "20260515")]

    assert features["candidate_shadow_score"]["grade"] == "S"
    assert features["entry_quality"]["score"] == 72


def test_observation_feature_map_keeps_cross_market_code_shape() -> None:
    rows = [
        {
            "trade_date": "2026-05-15",
            "code": "00700",
            "features_json": '{"candidate_shadow_score":{"score":82,"grade":"S"}}',
        }
    ]

    features = _observation_feature_map(rows, market="hk")

    assert ("00700", "20260515") in features
    assert ("000700", "20260515") not in features


def _event(
    rec_date: int,
    code: str,
    *,
    ai: bool,
    score: float,
    count: int,
    hit: bool,
    shadow: float | None = None,
    entry: float | None = None,
) -> dict:
    event = {
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
    if shadow is not None:
        event["candidate_shadow_score"] = shadow
    if entry is not None:
        event["entry_quality_score"] = entry
    return event
