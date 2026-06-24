from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from workflows.tail_buy_runtime import (
    build_llm_routes,
    build_tail_buy_runtime_config,
    default_tail_buy_portfolio_id,
    plan_intraday_scan_budget,
)
from workflows.tail_buy_utils import TZ


def test_plan_intraday_scan_budget_caps_over_limit_buffer() -> None:
    assert plan_intraday_scan_budget(12, limit_per_min=30, max_over_limit_symbols=5, force_over_limit=True) == (12, 0)
    assert plan_intraday_scan_budget(50, limit_per_min=30, max_over_limit_symbols=5, force_over_limit=True) == (35, 5)
    assert plan_intraday_scan_budget(50, limit_per_min=30, max_over_limit_symbols=5, force_over_limit=False) == (30, 0)


def test_default_tail_buy_portfolio_id_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("TAIL_BUY_PORTFOLIO_ID", "TAIL:main")
    monkeypatch.setenv("SUPABASE_USER_ID", "user-1")

    assert default_tail_buy_portfolio_id() == "TAIL:main"


def test_default_tail_buy_portfolio_id_falls_back_to_user(monkeypatch) -> None:
    monkeypatch.delenv("TAIL_BUY_PORTFOLIO_ID", raising=False)
    monkeypatch.setenv("SUPABASE_USER_ID", "user-1")

    assert default_tail_buy_portfolio_id() == "USER_LIVE:user-1"


def test_build_llm_routes_appends_unique_nvidia_kimi(monkeypatch) -> None:
    monkeypatch.setenv("EFFICIENCY_API_KEY", "eff-key")
    monkeypatch.setenv("EFFICIENCY_MODEL", "eff-model")
    monkeypatch.setenv("EFFICIENCY_BASE_URL", "https://eff.example/v1")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvidia-key")
    monkeypatch.setenv("NVIDIA_MODEL_KIMI", "kimi-model")

    routes = build_llm_routes(primary_provider="efficiency")

    assert [route["name"] for route in routes] == ["efficiency:eff-model", "nvidia-kimi:kimi-model"]


def test_build_tail_buy_runtime_config_uses_env_and_args(monkeypatch) -> None:
    monkeypatch.setenv("TAIL_BUY_LLM_PROVIDER", "efficiency")
    monkeypatch.setenv("EFFICIENCY_API_KEY", "eff-key")
    monkeypatch.setenv("EFFICIENCY_MODEL", "eff-model")
    monkeypatch.setenv("EFFICIENCY_BASE_URL", "https://eff.example/v1")
    monkeypatch.setenv("TAIL_BUY_INTRADAY_LIMIT_PER_MIN", "12")

    args = SimpleNamespace(deadline_minute=7, logs=None, max_llm_symbols=3, portfolio_id="USER_LIVE:test")
    started_at = datetime(2026, 6, 22, 14, 0, tzinfo=TZ)

    config = build_tail_buy_runtime_config(args, started_at)

    assert config.deadline_min == 7
    assert config.primary_route == "efficiency:eff-model"
    assert config.max_llm_symbols == 3
    assert config.intraday_limit_per_min == 12
    assert config.portfolio_id == "USER_LIVE:test"
