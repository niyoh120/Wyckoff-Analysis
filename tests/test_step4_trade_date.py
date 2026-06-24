from datetime import date
from types import SimpleNamespace

import workflows.step4_results as step4_results
from workflows import step4_portfolio
from workflows import step4_rebalancer as step4
from workflows.step4_models import DecisionItem, ExecutionTicket, PositionItem
from workflows.step4_order_config import step4_order_config_from_env
from workflows.step4_order_engine import WyckoffOrderEngine
from workflows.step4_runtime_config import step4_runtime_config_from_env


def _decision(action: str, *, is_add_on: bool = False) -> DecisionItem:
    return DecisionItem(
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


def _ticket(
    *,
    code: str = "000001",
    status: str = "APPROVED",
    effective_stop_loss: float | None = 8.8,
    audit: str = "risk-ok",
) -> ExecutionTicket:
    return ExecutionTicket(
        code=code,
        name="平安银行",
        action="HOLD",
        status=status,
        shares=1000,
        price_hint=9.5,
        amount=9500.0,
        stop_loss=8.9,
        max_loss=600.0,
        drawdown_ratio=0.06,
        reason="系统风控",
        tape_condition="放量站回VWAP",
        invalidate_condition="跌破VWAP",
        is_holding=True,
        atr14=0.2,
        original_stop_loss=8.7,
        effective_stop_loss=effective_stop_loss,
        slippage_bps=5.0,
        audit=audit,
    )


def test_step4_trade_context_uses_latest_market_trade_date(monkeypatch):
    monkeypatch.setattr(step4, "resolve_end_calendar_day", lambda: date(2026, 5, 17))
    runtime_config = step4.Step4RuntimeConfig()

    def fake_resolve_trading_window(end_calendar_day, trading_days):
        assert end_calendar_day == date(2026, 5, 17)
        assert trading_days == runtime_config.trading_days
        return SimpleNamespace(end_trade_date=date(2026, 5, 15))

    monkeypatch.setattr(step4, "resolve_trading_window", fake_resolve_trading_window)

    end_day, window, trade_date = step4._resolve_step4_trade_context(runtime_config)

    assert end_day == date(2026, 5, 17)
    assert window.end_trade_date == date(2026, 5, 15)
    assert trade_date == "2026-05-15"


def test_existing_position_probe_is_treated_as_add_on_and_requires_profit():
    engine = WyckoffOrderEngine(
        total_equity=100000,
        free_cash=50000,
        position_map={
            "000001": PositionItem(
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


def test_order_engine_uses_explicit_buy_block_config():
    engine = WyckoffOrderEngine(
        total_equity=100000,
        free_cash=50000,
        position_map={},
        latest_price_map={"000001": 9.5},
        atr_map={"000001": 0.2},
        market_regime="NEUTRAL",
        config=step4.Step4OrderConfig(buy_block_regimes=frozenset({"NEUTRAL"})),
    )

    tickets, cash = engine.process([_decision("PROBE")])

    assert cash == 50000
    assert tickets[0].status == "NO_TRADE"
    assert "regime=NEUTRAL" in tickets[0].reason


def test_step4_order_config_from_env_normalizes_values(monkeypatch):
    monkeypatch.setenv("STEP4_BUY_STOP_MODE", "bad")
    monkeypatch.setenv("STEP4_PROBE_BUDGET_LIMIT", "-1")
    monkeypatch.setenv("STEP4_ATTACK_BUDGET_LIMIT", "2")
    monkeypatch.setenv("STEP4_BUY_BLOCK_REGIMES", "CRASH,COOLDOWN,neutral")

    cfg = step4_order_config_from_env()

    assert cfg.buy_stop_mode == "floor"
    assert cfg.probe_budget_limit == 0.0
    assert cfg.attack_budget_limit == 1.0
    assert cfg.buy_block_regimes == frozenset({"CRASH", "NEUTRAL"})


def test_step4_runtime_config_from_env_normalizes_values(monkeypatch):
    monkeypatch.setenv("STEP4_TRADING_DAYS", "0")
    monkeypatch.setenv("STEP4_MAX_OUTPUT_TOKENS", "bad")
    monkeypatch.setenv("STEP4_MAX_WORKERS", "-2")
    monkeypatch.setenv("STEP4_MAX_NEW_BUYS_RISK_ON", "-1")
    monkeypatch.setenv("STEP4_MAX_NEW_BUYS_CAUTION", "3")
    monkeypatch.setenv("STEP4_ENFORCE_TARGET_TRADE_DATE", "yes")

    cfg = step4_runtime_config_from_env()

    assert cfg.trading_days == 1
    assert cfg.max_output_tokens == 8192
    assert cfg.max_workers == 1
    assert cfg.new_buy_limits.risk_on == 0
    assert cfg.new_buy_limits.caution == 3
    assert cfg.enforce_target_trade_date is True


def test_step4_portfolio_loads_env_state_and_skips_invalid_positions(monkeypatch):
    monkeypatch.setenv(
        "MY_PORTFOLIO_STATE",
        """
        {
          "free_cash": 12345.6,
          "total_equity": 20000,
          "positions": [
            {"code": "000001", "name": "平安银行", "cost": 10, "shares": 1000, "buy_dt": "2026-05-10"},
            {"code": "bad", "shares": 1},
            "not-object"
          ]
        }
        """,
    )

    portfolio = step4_portfolio.load_portfolio_from_env()

    assert portfolio.free_cash == 12345.6
    assert portfolio.total_equity == 20000
    assert [p.code for p in portfolio.positions] == ["000001"]
    assert step4_portfolio.portfolio_state_signature(portfolio)


def test_send_trade_ticket_fails_when_telegram_fails(monkeypatch):
    captured: dict[str, bool | str] = {}
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(
        step4,
        "send_to_telegram",
        lambda message, **_kwargs: captured.update({"telegram": True, "message": message}) and False,
    )

    assert step4._send_trade_ticket("# ticket", "token", "chat") is False
    assert captured == {"telegram": True, "message": "# ticket"}


def test_send_trade_ticket_uses_only_telegram_even_when_feishu_env_exists(monkeypatch):
    captured: dict[str, bool | str] = {}
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(
        step4,
        "send_to_telegram",
        lambda message, **_kwargs: captured.update({"telegram": True, "message": message}) or True,
    )

    assert step4._send_trade_ticket("# ticket", "token", "chat") is True
    assert captured == {"telegram": True, "message": "# ticket"}


def test_send_trade_ticket_requires_telegram(monkeypatch):
    captured: dict[str, bool] = {}
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(step4, "send_to_telegram", lambda *_args, **_kwargs: captured.update({"telegram": True}))

    assert step4._send_trade_ticket("# ticket", "", "") is False
    assert captured == {}


def test_step4_result_record_updates_stops_and_builds_ticket_rows(monkeypatch):
    calls: list[tuple[str, list[dict]]] = []
    monkeypatch.setattr(
        step4_results,
        "update_position_stops",
        lambda portfolio_id, updates: calls.append((portfolio_id, updates)) or True,
    )

    record = step4_results.prepare_step4_result_record(
        portfolio_id="P1",
        tickets=[_ticket()],
        state_signature="ABC123",
    )

    assert "_sigabc123" in record.run_id
    assert calls == [("P1", [{"code": "000001", "stop_loss": 8.8}])]
    assert record.ticket_rows[0]["reason"] == "系统风控 | audit=risk-ok"


def test_step4_save_orders_and_nav_uses_persistence_boundaries(monkeypatch):
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        step4_results,
        "save_ai_trade_orders",
        lambda **kwargs: calls.setdefault("orders", kwargs) is not None,
    )
    monkeypatch.setattr(
        step4_results,
        "cancel_trade_orders",
        lambda **kwargs: calls.setdefault("cancel", kwargs) or 1,
    )
    monkeypatch.setattr(
        step4_results,
        "upsert_daily_nav",
        lambda **kwargs: calls.setdefault("nav", kwargs) is not None,
    )
    options = SimpleNamespace(portfolio_id="P1", model="model-x")
    context = SimpleNamespace(trade_date="2026-05-15", total_equity=120000.0)

    step4_results.save_step4_orders_and_nav(
        options=options,
        context=context,
        run_id="run-1",
        rendered_market_view="市场视图",
        ticket_rows=[{"code": "000001"}],
        free_cash_after=50000.0,
    )

    assert calls["orders"] == {
        "run_id": "run-1",
        "portfolio_id": "P1",
        "model": "model-x",
        "trade_date": "2026-05-15",
        "market_view": "市场视图",
        "orders": [{"code": "000001"}],
    }
    assert calls["cancel"] == {
        "portfolio_id": "P1",
        "trade_date": "2026-05-15",
        "exclude_run_id": "run-1",
    }
    assert calls["nav"] == {
        "portfolio_id": "P1",
        "trade_date": "2026-05-15",
        "free_cash": 50000.0,
        "total_equity": 120000.0,
        "positions_value": 70000.0,
    }
