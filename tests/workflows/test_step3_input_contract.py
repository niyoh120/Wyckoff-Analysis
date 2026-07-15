from __future__ import annotations

from core.market_trade_mode import resolve_market_trade_mode
from workflows.daily_job_persistence import step3_review_symbols
from workflows.daily_job_step3 import filter_confirmed_step3_codes
from workflows.step3_reporting import _empty_step3_report, _step3_title


def test_mainline_step3_uses_displayed_funnel_selection_before_confirmation() -> None:
    symbols = [
        {"code": "000003", "signal_status": "confirmed", "candidate_lane": "mainline"},
        {"code": "000001", "name": "候选一", "candidate_lane": "trend"},
        {"code": "000002", "name": "候选二", "candidate_lane": "accum"},
    ]
    details = {"selected_for_ai": ["000002", "000001"]}

    rows = step3_review_symbols(
        symbols,
        step2_details=details,
        trade_mode=resolve_market_trade_mode("NEUTRAL"),
    )

    assert [row["code"] for row in rows] == ["000002", "000001"]
    assert [row["input_order"] for row in rows] == [0, 1]


def test_unconfirmed_step3_verdict_still_cannot_reach_execution() -> None:
    kept, blocked = filter_confirmed_step3_codes(
        ["000001", "000002"],
        [
            {"code": "000001", "signal_status": "pending"},
            {"code": "000002", "signal_status": "confirmed"},
        ],
    )

    assert kept == ["000002"]
    assert blocked == ["000001"]


def test_empty_step3_report_states_real_upstream_reason() -> None:
    report = _empty_step3_report("", [], input_count=0)

    assert "本轮未执行三阵营模型审判" in report
    assert "上游实际送入 Step3 的候选为 0" in report
    assert "候选均被 RAG" not in report
    assert "风险过高" not in report


def test_step3_title_uses_report_trade_date_instead_of_wall_clock() -> None:
    assert _step3_title({"trade_date": "2026-07-15"}) == "📄 批量研报 2026-07-15"
