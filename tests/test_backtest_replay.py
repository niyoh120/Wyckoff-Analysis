from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

from core.backtest_execution import ExitSimulationConfig
from core.backtest_replay import BacktestReplayConfig, replay_backtest
from core.mainline_engine import MainlineEngineConfig
from core.wyckoff_engine import FunnelConfig, FunnelResult


def _hist() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [date(2026, 1, day) for day in range(1, 6)],
            "open": [10.0, 11.0, 12.0, 13.0, 14.0],
            "high": [10.5, 11.5, 12.5, 13.5, 14.5],
            "low": [9.5, 10.5, 11.5, 12.5, 13.5],
            "close": [10.2, 11.2, 12.2, 13.2, 14.2],
            "volume": [1000, 1100, 1200, 1300, 1400],
            "amount": [10_000, 11_000, 12_000, 13_000, 14_000],
            "pct_chg": [0, 1, 1, 1, 1],
        }
    )


def _result() -> FunnelResult:
    return FunnelResult(
        layer1_symbols=["000001"],
        layer2_symbols=["000001"],
        layer3_symbols=["000001"],
        top_sectors=[],
        triggers={"sos": [("000001", 2.0)]},
        stage_map={},
        markup_symbols=[],
        exit_signals={},
        channel_map={"000001": "点火破局"},
        leader_radar_symbols=[],
        leader_radar_rows=[],
    )


def _config() -> BacktestReplayConfig:
    return BacktestReplayConfig(
        trading_days=3,
        hold_days=1,
        board="all",
        top_n=1,
        selection_mode="all_formal_l4",
        full_formal_l4_max=10,
        regime_filter=False,
        pending_mode="off",
        pending_merge_order="funnel_first",
        abc_filter=False,
        entry_price_mode="open",
        entry_price_time="14:55",
        entry_price_fallback="close",
        buy_friction_pct=0.0,
        sell_friction_pct=0.0,
        max_atr_hold_days=120,
        exit=ExitSimulationConfig(
            exit_mode="close_only",
            stop_loss_pct=0.0,
            take_profit_pct=0.0,
            trailing_stop_pct=0.0,
            trailing_activate_pct=0.0,
            sltp_priority="stop_first",
            atr_period=14,
            atr_multiplier=2.0,
            atr_hard_stop_pct=-9.0,
        ),
    )


def test_replay_backtest_generates_t1_trades(monkeypatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr("core.backtest_replay.calc_market_breadth", lambda _df_map: {})
    monkeypatch.setattr(
        "core.backtest_replay.analyze_benchmark_and_tune_cfg", lambda *_args, **_kwargs: {"regime": "NEUTRAL"}
    )

    def fake_run_funnel(**kwargs):
        calls.update(kwargs)
        return _result()

    monkeypatch.setattr("core.backtest_replay.run_funnel", fake_run_funnel)
    cfg = FunnelConfig(trading_days=3)
    cfg.ma_long = 2
    replay_cfg = replace(
        _config(),
        concept_map={"000001": ["CPO"]},
        concept_heat=[{"name": "CPO", "pct": 3.2}],
        financial_map={"000001": {"roe": 12}},
        mainline_config=MainlineEngineConfig(max_ai_candidates=2),
    )

    replay = replay_backtest(
        all_df_map={"000001": _hist()},
        bench_df=_hist(),
        trade_dates=[date(2026, 1, day) for day in range(1, 6)],
        name_map={"000001": "平安银行"},
        market_cap_map={},
        sector_map={},
        base_cfg=cfg,
        config=replay_cfg,
    )

    assert replay.eval_days == 2
    assert replay.signal_days == 2
    assert replay.pending_confirmed_total == 0
    assert [record.trigger for record in replay.records] == ["sos", "sos"]
    assert replay.records[0].entry_date == date(2026, 1, 3)
    assert replay.records[0].exit_date == date(2026, 1, 4)
    assert replay.records[0].ret_pct == pytest.approx(10.0)
    assert calls["concept_map"] == {"000001": ["CPO"]}
    assert calls["concept_heat"] == [{"name": "CPO", "pct": 3.2}]
    assert calls["financial_map"] == {"000001": {"roe": 12}}
    assert calls["mainline_config"].max_ai_candidates == 2
