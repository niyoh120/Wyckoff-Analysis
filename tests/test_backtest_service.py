from __future__ import annotations

from datetime import date

import pandas as pd

from workflows.backtest import BacktestWorkflowRequest, run_backtest_request
from workflows.backtest_data import BacktestHistory, BacktestMetadata, BacktestUniverse


def test_run_backtest_workflow_builds_context_without_network(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("FUNNEL_SMALLCAP_BENCH_CODE", "399905")

    monkeypatch.setattr(
        "workflows.backtest.resolve_backtest_universe",
        lambda *_args, **_kwargs: BacktestUniverse(["000001"], {"000001": "平安银行"}, "test"),
    )
    monkeypatch.setattr(
        "workflows.backtest.load_backtest_history",
        lambda **_kwargs: BacktestHistory({"000001": pd.DataFrame()}, pd.DataFrame(), [], 3, True),
    )
    monkeypatch.setattr(
        "workflows.backtest.load_backtest_metadata",
        lambda *_args, **_kwargs: BacktestMetadata(
            {"000001": 100.0},
            {"000001": "银行"},
            {"000001": ["CPO"]},
            [{"name": "CPO", "pct": 3.2}],
            {"000001": {"roe": 12}},
            "test",
        ),
    )

    def fake_execute_backtest_run(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame(), {"ok": True}

    monkeypatch.setattr("workflows.backtest.execute_backtest_run", fake_execute_backtest_run)

    trades, summary = run_backtest_request(
        BacktestWorkflowRequest(
            start_dt=date(2026, 1, 1),
            end_dt=date(2026, 1, 31),
            hold_days=10,
            top_n=4,
            board="all",
            sample_size=0,
            trading_days=320,
            max_workers=1,
            cash_portfolio=True,
            portfolio_styles="confirmation_only",
        )
    )

    assert trades.empty
    assert summary == {"ok": True}
    assert captured["context"].board == "all"
    assert captured["data"].name_map == {"000001": "平安银行"}
    assert captured["data"].concept_map == {"000001": ["CPO"]}
    assert captured["data"].concept_heat == [{"name": "CPO", "pct": 3.2}]
    assert captured["data"].financial_map == {"000001": {"roe": 12}}
    assert captured["config"].performance.cash_portfolio is True
    analyzer = captured["config"].replay.market_regime_analyzer
    assert analyzer.keywords["regime_config"].smallcap_bench_code == "399905"
