from __future__ import annotations

from workflows.step3_candidates import _base_candidate_fields


def test_base_candidate_fields_preserves_candidate_attribution() -> None:
    row = _base_candidate_fields(
        0,
        {
            "code": "300308",
            "name": "中际旭创",
            "strategy_version": "candidate_lane_v1",
            "candidate_lane": "mainline",
            "entry_type": "主线平台再突破",
            "mainline_score": 0.86,
            "timing_score": 0.72,
        },
    )

    assert row["candidate_lane"] == "mainline"
    assert row["entry_type"] == "主线平台再突破"
    assert row["mainline_score"] == 0.86
    assert row["timing_score"] == 0.72
