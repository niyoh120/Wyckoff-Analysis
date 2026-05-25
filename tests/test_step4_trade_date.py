from datetime import date
from types import SimpleNamespace

from scripts import step4_rebalancer as step4


def _decision(action: str, *, is_add_on: bool = False) -> step4.DecisionItem:
    return step4.DecisionItem(
        code="000001",
        name="平安银行",
        action=action,
        entry_zone_min=9.4,
        entry_zone_max=9.7,
        stop_loss=8.9,
        trim_ratio=None,
        tape_condition="放量站回VWAP",
        invalidate_condition="跌破VWAP",
        is_add_on=is_add_on,
        reason="模型建议加仓",
        confidence=0.8,
    )


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


def test_existing_position_probe_is_treated_as_add_on_and_requires_profit():
    engine = step4.WyckoffOrderEngine(
        total_equity=100000,
        free_cash=50000,
        position_map={
            "000001": step4.PositionItem(
                code="000001",
                name="平安银行",
                cost=10.0,
                buy_dt="2026-05-10",
                shares=1000,
                stop_loss=8.8,
            )
        },
        latest_price_map={"000001": 9.5},
        atr_map={"000001": 0.2},
        market_regime="NEUTRAL",
    )

    tickets, _cash = engine.process([_decision("PROBE", is_add_on=False)])

    assert tickets[0].action == "HOLD"
    assert tickets[0].status == "APPROVED"
    assert "当前未浮盈" in tickets[0].reason
