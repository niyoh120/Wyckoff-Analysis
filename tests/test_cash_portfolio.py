from __future__ import annotations

from datetime import date

import pandas as pd

from core.cash_portfolio import CashPortfolioConfig, calc_commission, expand_portfolio_styles, simulate_cash_portfolio


def test_commission_uses_small_trade_fee() -> None:
    cfg = CashPortfolioConfig(
        commission_rate=0.0002,
        small_trade_threshold=10_000,
        small_trade_fee=5,
    )

    assert calc_commission(5_000, cfg) == 5.0
    assert calc_commission(10_000, cfg) == 2.0
    assert calc_commission(100_000, cfg) == 20.0


def test_cash_portfolio_limits_positions_and_lot_size() -> None:
    rows = []
    for idx in range(5):
        rows.append(
            {
                "code": f"00000{idx}",
                "name": f"S{idx}",
                "signal_date": "2026-01-02",
                "entry_date": "2026-01-05",
                "exit_date": "2026-01-10",
                "entry_close": 10.0,
                "exit_close": 11.0,
            }
        )

    closed, nav, summary = simulate_cash_portfolio(
        pd.DataFrame(rows),
        CashPortfolioConfig(
            initial_cash=100_000,
            max_positions=4,
            commission_rate=0.0002,
            small_trade_threshold=10_000,
            small_trade_fee=5,
            lot_size=100,
        ),
    )

    assert len(closed) == 4
    assert set(closed["shares"]) == {2400}
    assert summary["cash_portfolio_skipped_full"] == 1
    assert summary["cash_portfolio_win_rate_pct"] == 100.0
    assert summary["cash_portfolio_final_cash"] > 109_000
    assert not nav.empty


def test_cash_portfolio_accepts_empty_trade_frame() -> None:
    closed, nav, summary = simulate_cash_portfolio(pd.DataFrame(), CashPortfolioConfig(initial_cash=100_000))

    assert closed.empty
    assert nav.empty
    assert summary["cash_portfolio_final_cash"] == 100_000
    assert summary["cash_portfolio_trades"] == 0


def test_portfolio_style_probe_add_allows_same_stock_addon() -> None:
    rows = [
        {
            "code": "000001",
            "name": "S1",
            "signal_date": "2026-01-02",
            "entry_date": "2026-01-05",
            "exit_date": "2026-01-20",
            "entry_close": 10.0,
            "exit_close": 11.0,
            "score": 1.0,
        },
        {
            "code": "000001",
            "name": "S1",
            "signal_date": "2026-01-06",
            "entry_date": "2026-01-07",
            "exit_date": "2026-01-22",
            "entry_close": 10.5,
            "exit_close": 11.5,
            "score": 1.2,
        },
    ]

    closed, _nav, summary = simulate_cash_portfolio(
        pd.DataFrame(rows),
        CashPortfolioConfig(initial_cash=100_000, portfolio_style="probe_add"),
    )

    assert list(closed["entry_kind"]) == ["probe", "add"]
    assert summary["cash_portfolio_probe_entries"] == 1
    assert summary["cash_portfolio_add_entries"] == 1


def test_portfolio_style_confirmation_waits_for_second_signal() -> None:
    rows = [
        {
            "code": "000001",
            "name": "S1",
            "signal_date": "2026-01-02",
            "entry_date": "2026-01-05",
            "exit_date": "2026-01-20",
            "entry_close": 10.0,
            "exit_close": 11.0,
            "score": 1.0,
        },
        {
            "code": "000001",
            "name": "S1",
            "signal_date": "2026-01-06",
            "entry_date": "2026-01-07",
            "exit_date": "2026-01-22",
            "entry_close": 10.5,
            "exit_close": 11.5,
            "score": 1.2,
        },
    ]

    closed, _nav, summary = simulate_cash_portfolio(
        pd.DataFrame(rows),
        CashPortfolioConfig(initial_cash=100_000, portfolio_style="confirmation_only"),
    )

    assert list(closed["entry_kind"]) == ["confirmed"]
    assert summary["cash_portfolio_observation_wait"] == 1
    assert summary["cash_portfolio_confirmed_entries"] == 1


def test_portfolio_style_concentrated_swap_replaces_weak_holding() -> None:
    rows = [
        {
            "code": "000001",
            "name": "S1",
            "signal_date": "2026-01-02",
            "entry_date": "2026-01-05",
            "exit_date": "2026-02-01",
            "entry_close": 10.0,
            "exit_close": 9.0,
            "score": 1.0,
        },
        {
            "code": "000002",
            "name": "S2",
            "signal_date": "2026-01-02",
            "entry_date": "2026-01-05",
            "exit_date": "2026-02-01",
            "entry_close": 10.0,
            "exit_close": 9.0,
            "score": 1.1,
        },
        {
            "code": "000003",
            "name": "S3",
            "signal_date": "2026-01-06",
            "entry_date": "2026-01-07",
            "exit_date": "2026-02-03",
            "entry_close": 10.0,
            "exit_close": 12.0,
            "score": 2.0,
        },
    ]

    closed, _nav, summary = simulate_cash_portfolio(
        pd.DataFrame(rows),
        CashPortfolioConfig(initial_cash=100_000, portfolio_style="concentrated_swap"),
        mark_price_fn=lambda code, day: 10.2 if code == "000001" and day == date(2026, 1, 7) else None,
    )

    assert "style_swap" in set(closed["exit_reason"])
    assert "000003" in set(closed["code"])
    assert summary["cash_portfolio_style_swaps"] == 1


def test_expand_portfolio_styles_preset() -> None:
    assert expand_portfolio_styles("all_core") == [
        "slot_equal_4",
        "probe_add",
        "confirmation_only",
        "trend_pyramid",
        "concentrated_swap",
    ]
