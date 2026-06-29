from __future__ import annotations

import pandas as pd

from workflows.step3_runtime_config import Step3RuntimeConfig
from workflows.step3_upstream_selection import select_upstream_priority_candidates


def test_upstream_priority_selection_uses_priority_score_under_cap() -> None:
    candidates = pd.DataFrame(
        [
            {"code": "T_LOW", "track": "Trend", "input_order": 0, "priority_score": 10.0},
            {"code": "T_HIGH", "track": "Trend", "input_order": 1, "priority_score": 90.0},
            {"code": "A_HIGH", "track": "Accum", "input_order": 2, "priority_score": 80.0},
            {"code": "A_LOW", "track": "Accum", "input_order": 3, "priority_score": 20.0},
        ]
    )

    selected = select_upstream_priority_candidates(candidates, Step3RuntimeConfig(), context_cap=2)

    assert selected["code"].tolist() == ["T_HIGH", "A_HIGH"]


def test_upstream_priority_selection_keeps_priority_order_after_cap() -> None:
    candidates = pd.DataFrame(
        [
            {"code": "T_MID", "track": "Trend", "input_order": 0, "priority_score": 50.0},
            {"code": "T_LOW", "track": "Trend", "input_order": 1, "priority_score": 10.0},
            {"code": "T_HIGH", "track": "Trend", "input_order": 2, "priority_score": 90.0},
        ]
    )

    selected = select_upstream_priority_candidates(candidates, Step3RuntimeConfig(), context_cap=2)

    assert selected["code"].tolist() == ["T_HIGH", "T_MID"]


def test_upstream_priority_selection_preserves_input_order_without_scores() -> None:
    candidates = pd.DataFrame(
        [
            {"code": "T_FIRST", "track": "Trend", "input_order": 0, "priority_score": pd.NA},
            {"code": "T_SECOND", "track": "Trend", "input_order": 1, "priority_score": pd.NA},
            {"code": "A_FIRST", "track": "Accum", "input_order": 2, "priority_score": pd.NA},
            {"code": "A_SECOND", "track": "Accum", "input_order": 3, "priority_score": pd.NA},
        ]
    )

    selected = select_upstream_priority_candidates(candidates, Step3RuntimeConfig(), context_cap=2)

    assert selected["code"].tolist() == ["T_FIRST", "A_FIRST"]
