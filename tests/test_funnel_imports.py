from __future__ import annotations

import pytest

akshare = pytest.importorskip("akshare", reason="akshare not installed")


def test_funnel_tool_imports_are_direct() -> None:
    from core.candidate_ranker import TRIGGER_LABELS, rank_l3_candidates
    from core.market_breadth import calc_market_breadth
    from tools.market_regime import analyze_benchmark_and_tune_cfg

    assert isinstance(TRIGGER_LABELS, (dict, list, tuple))
    assert callable(analyze_benchmark_and_tune_cfg)
    assert callable(calc_market_breadth)
    assert callable(rank_l3_candidates)


def test_funnel_workflow_exports() -> None:
    from workflows.wyckoff_funnel import run, run_funnel_job

    assert callable(run)
    assert callable(run_funnel_job)
