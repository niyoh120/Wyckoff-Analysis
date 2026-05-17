from datetime import date
from types import SimpleNamespace

from scripts import step4_rebalancer as step4


def test_step4_trade_context_uses_latest_market_trade_date(monkeypatch):
    monkeypatch.setattr(step4, "resolve_end_calendar_day", lambda: date(2026, 5, 17))

    def fake_resolve_trading_window(end_calendar_day, trading_days):
        assert end_calendar_day == date(2026, 5, 17)
        assert trading_days == step4.TRADING_DAYS
        return SimpleNamespace(end_trade_date=date(2026, 5, 15))

    monkeypatch.setattr(step4, "_resolve_trading_window", fake_resolve_trading_window)

    end_day, window, trade_date = step4._resolve_step4_trade_context()

    assert end_day == date(2026, 5, 17)
    assert window.end_trade_date == date(2026, 5, 15)
    assert trade_date == "2026-05-15"
