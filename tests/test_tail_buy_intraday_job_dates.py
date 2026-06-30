from __future__ import annotations

from datetime import date, datetime

from integrations.fetch_a_share_csv import TradingWindow
from workflows import tail_buy_candidates
from workflows.tail_buy_utils import TZ


def test_resolve_trade_dates_on_trading_day_uses_prev_trade_and_today(monkeypatch):
    monkeypatch.setattr(
        tail_buy_candidates,
        "current_time",
        lambda: datetime(2026, 4, 27, 14, 10, tzinfo=TZ),  # 周一交易时段
    )

    def fake_window(*, end_calendar_day: date, trading_days: int) -> TradingWindow:
        assert end_calendar_day == date(2026, 4, 27)
        assert trading_days == 2
        return TradingWindow(
            start_trade_date=date(2026, 4, 24),  # 上周五
            end_trade_date=date(2026, 4, 27),  # 周一
        )

    monkeypatch.setattr(tail_buy_candidates, "resolve_trading_window", fake_window)
    prev_trade, today_trade = tail_buy_candidates.resolve_tail_buy_trade_dates()
    assert prev_trade == "2026-04-24"
    assert today_trade == "2026-04-27"


def test_resolve_trade_dates_on_non_trading_day_targets_latest_trade(monkeypatch):
    monkeypatch.setattr(
        tail_buy_candidates,
        "current_time",
        lambda: datetime(2026, 4, 26, 10, 0, tzinfo=TZ),  # 周日
    )

    def fake_window(*, end_calendar_day: date, trading_days: int) -> TradingWindow:
        assert end_calendar_day == date(2026, 4, 26)
        assert trading_days == 2
        return TradingWindow(
            start_trade_date=date(2026, 4, 23),
            end_trade_date=date(2026, 4, 24),  # 最新交易日（周五）
        )

    monkeypatch.setattr(tail_buy_candidates, "resolve_trading_window", fake_window)
    prev_trade, today_trade = tail_buy_candidates.resolve_tail_buy_trade_dates()
    assert prev_trade == "2026-04-24"
    assert today_trade == "2026-04-24"


def test_resolve_trade_dates_fallback_to_natural_day_when_calendar_fails(monkeypatch):
    monkeypatch.setattr(
        tail_buy_candidates,
        "current_time",
        lambda: datetime(2026, 4, 27, 14, 10, tzinfo=TZ),
    )

    def fake_window(*, end_calendar_day: date, trading_days: int) -> TradingWindow:
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(tail_buy_candidates, "resolve_trading_window", fake_window)
    prev_trade, today_trade = tail_buy_candidates.resolve_tail_buy_trade_dates()
    assert prev_trade == "2026-04-26"
    assert today_trade == "2026-04-27"


def test_load_tail_candidates_strict_signal_date_uses_exact_query(monkeypatch):
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(tail_buy_candidates, "is_admin_configured", lambda: True)
    monkeypatch.setattr(tail_buy_candidates, "_load_holding_candidates", lambda *_args, **_kwargs: [])

    def fake_fetch(cutoff_date: str, *, exact_date: str | None = None) -> list[dict]:
        calls.append((cutoff_date, exact_date))
        return [
            {
                "code": "000001",
                "name": "平安银行",
                "signal_type": "sos",
                "signal_score": 80,
                "status": "confirmed",
                "signal_date": "2026-06-29",
            }
        ]

    monkeypatch.setattr(tail_buy_candidates, "_fetch_signal_pending_rows", fake_fetch)

    candidates, source = tail_buy_candidates.load_tail_candidates(
        "2026-06-29",
        "USER_LIVE:test",
        strict_signal_date=True,
        include_holdings=False,
        lookback_days=0,
    )

    assert calls == [("2026-06-29", "2026-06-29")]
    assert [item.code for item in candidates] == ["000001"]
    assert "signal_pending_exact=1" in source
