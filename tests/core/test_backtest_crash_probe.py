from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from core.backtest_crash_probe import build_crash_probe_observations, summarize_crash_probe_replay


def _history(last_closes: tuple[float, float, float, float] = (10.0, 10.1, 10.2, 11.0)) -> pd.DataFrame:
    start = date(2026, 1, 1)
    closes = [10.0] * 56 + list(last_closes)
    rows = []
    for idx, close in enumerate(closes):
        rows.append(
            {
                "date": start + timedelta(days=idx),
                "open": close - 0.1,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
                "volume": 1000.0,
            }
        )
    rows[-3].update({"open": 9.9, "high": 10.2, "low": 9.8, "close": 10.1})
    return pd.DataFrame(rows)


def test_daily_proxy_selects_top1_after_support_reclaim() -> None:
    signal_date = _history().iloc[-4]["date"]
    histories = {"000001": _history(), "000002": _history()}
    day_map = {code: df[df["date"] <= signal_date] for code, df in histories.items()}

    observations = build_crash_probe_observations(
        "CRASH",
        signal_date,
        {"crash_resilience_watch": [("000001", 8.0), ("000002", 9.0)]},
        day_map,
    )

    assert len(observations) == 2
    stats = summarize_crash_probe_replay(
        observations,
        histories,
        _history()["date"].tail(4).tolist(),
        hold_days=1,
        buy_friction_pct=0.0,
        sell_friction_pct=0.0,
    )

    assert stats["proxy_qualified"] == 2
    assert stats["staged_entries"] == 1


def test_staged_replay_reports_2pct_probe_and_3pct_confirmation_add() -> None:
    history = _history()
    trade_dates = history["date"].tail(4).tolist()
    signal_date = trade_dates[0]
    observations = build_crash_probe_observations(
        "CRASH",
        signal_date,
        {"crash_resilience_watch": [("000001", 9.0)]},
        {"000001": history[history["date"] <= signal_date]},
    )

    stats = summarize_crash_probe_replay(
        observations,
        {"000001": history},
        trade_dates,
        hold_days=1,
        buy_friction_pct=0.0,
        sell_friction_pct=0.0,
    )

    assert stats["watch_candidates"] == 1
    assert stats["research_only"] is True
    assert stats["same_close_entry_proxy"] is True
    assert stats["signal_available_before_entry"] is True
    assert stats["portfolio_accounted"] is False
    assert stats["commission_included"] is False
    assert stats["staged_entries"] == 1
    assert stats["confirmed_next_day"] == 1
    assert stats["confirmation_rate_pct"] == 100.0
    assert stats["probe_2pct_capital_return_pct"] == pytest.approx((11.0 / 10.1 - 1.0) * 2.0)
    assert stats["confirmed_add_3pct_capital_return_pct"] == pytest.approx((11.0 / 10.2 - 1.0) * 3.0)


def test_daily_proxy_does_not_enter_without_support_breach() -> None:
    history = _history()
    signal_date = history.iloc[-4]["date"]
    day_map = history[history["date"] <= signal_date].copy()
    history.loc[history.index[-3], "low"] = 10.05

    observations = build_crash_probe_observations(
        "CRASH",
        signal_date,
        {"crash_resilience_watch": [("000001", 9.0)]},
        {"000001": day_map},
    )

    stats = summarize_crash_probe_replay(
        observations,
        {"000001": history},
        history["date"].tail(4).tolist(),
        hold_days=1,
        buy_friction_pct=0.0,
        sell_friction_pct=0.0,
    )

    assert stats["proxy_qualified"] == 0
    assert stats["staged_entries"] == 0
