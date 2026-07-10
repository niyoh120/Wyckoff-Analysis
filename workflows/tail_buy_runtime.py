"""Runtime configuration and planning helpers for the tail-buy job."""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from core.tail_buy.models import safe_float
from core.tail_buy.strategy import DECISION_BUY, DECISION_WATCH, TailBuyCandidate, TailBuyStrategyConfig
from integrations.llm_client import provider_fallbacks, provider_route_chain, resolve_provider_name
from workflows.tail_buy_config import tail_buy_strategy_config_from_env
from workflows.tail_buy_holding_models import HoldingStopConfig

TRUE_TEXTS = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LlmOverlayConfig:
    routes: list[dict[str, str]]
    style: str
    deadline_at: datetime
    depth_map: dict[str, dict]
    verbose_errors: bool


@dataclass
class LlmOverlayRunResult:
    decisions: dict[str, dict] = field(default_factory=dict)
    ok_count: int = 0
    route_hits: dict[str, int] = field(default_factory=dict)
    errors: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class TailBuyRuntimeConfig:
    started_at: datetime
    logs_path: str
    mode: str
    deadline_min: int
    deadline_at: datetime
    feishu_webhook: str
    tg_bot_token: str
    tg_chat_id: str
    provider: str
    llm_routes: list[dict[str, str]]
    tickflow_api_key: str
    style: str
    fetch_concurrency: int
    llm_concurrency: int
    max_llm_symbols: int
    llm_min_rule_score: float
    llm_allowed_rule_decisions: tuple[str, ...]
    intraday_limit_per_min: int
    max_over_limit_symbols: int
    force_over_limit: bool
    tickflow_task_retries: int
    use_batch_intraday: bool
    intraday_batch_size: int
    holding_stop_config: HoldingStopConfig
    portfolio_id: str
    strategy_config: TailBuyStrategyConfig

    @property
    def primary_route(self) -> str:
        return self.llm_routes[0]["name"] if self.llm_routes else "disabled"


@dataclass(frozen=True)
class TailBuyCandidateRun:
    merged: list[TailBuyCandidate]
    llm_total: int
    llm_success: int
    llm_route_stats: dict[str, int]
    data_fetched_at: str
    policy_weights: dict[str, float] = field(default_factory=dict)
    policy_weight_meta: dict[str, Any] = field(default_factory=dict)


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in TRUE_TEXTS


def default_tail_buy_portfolio_id() -> str:
    direct = str(os.getenv("TAIL_BUY_PORTFOLIO_ID", "") or "").strip()
    if direct:
        return direct
    user_id = str(os.getenv("SUPABASE_USER_ID", "") or "").strip()
    if user_id:
        return f"USER_LIVE:{user_id}"
    monitor = str(os.getenv("MONITOR_PORTFOLIO_ID", "") or "").strip()
    return monitor or "USER_LIVE"


def plan_intraday_scan_budget(
    total_candidates: int,
    *,
    limit_per_min: int,
    max_over_limit_symbols: int,
    force_over_limit: bool,
) -> tuple[int, int]:
    total = max(int(total_candidates), 0)
    limit = max(int(limit_per_min), 1)
    over = max(min(int(max_over_limit_symbols), 5), 0)
    if total <= limit:
        return total, 0
    if force_over_limit and over > 0:
        to_scan = min(total, limit + over)
        return to_scan, max(to_scan - limit, 0)
    return min(total, limit), 0


def build_llm_routes(*, primary_provider: str) -> list[dict[str, str]]:
    routes = provider_route_chain(primary_provider, provider_fallbacks("TAIL_BUY_LLM_FALLBACK_PROVIDERS"))
    seen = {(r["provider"], r["model"], r["base_url"]) for r in routes}
    _append_optional_nvidia_route(routes, seen)
    return routes


def build_tail_buy_runtime_config(args: Any, started_at: datetime) -> TailBuyRuntimeConfig:
    deadline_min = max(int(args.deadline_minute or 25), 5)
    provider = resolve_provider_name("TAIL_BUY_LLM_PROVIDER", "efficiency")
    mode = _tail_buy_mode_from_args(args)
    return TailBuyRuntimeConfig(
        started_at=started_at,
        logs_path=args.logs or default_tail_buy_logs_path(started_at),
        mode=mode,
        deadline_min=deadline_min,
        deadline_at=started_at + timedelta(minutes=deadline_min),
        feishu_webhook=os.getenv("FEISHU_WEBHOOK_URL", "").strip(),
        tg_bot_token=os.getenv("TG_BOT_TOKEN", "").strip(),
        tg_chat_id=os.getenv("TG_CHAT_ID", "").strip(),
        provider=provider,
        llm_routes=build_llm_routes(primary_provider=provider),
        tickflow_api_key=os.getenv("TICKFLOW_API_KEY", "").strip(),
        style=os.getenv("TAIL_BUY_STYLE", "auto").strip().lower() or "auto",
        fetch_concurrency=max(int(os.getenv("TAIL_BUY_FETCH_CONCURRENCY", "8")), 1),
        llm_concurrency=max(int(os.getenv("TAIL_BUY_LLM_CONCURRENCY", "4")), 1),
        max_llm_symbols=max(int(args.max_llm_symbols or 20), 0),
        llm_min_rule_score=max(safe_float(os.getenv("TAIL_BUY_LLM_MIN_RULE_SCORE", "60"), 60.0), 0.0),
        llm_allowed_rule_decisions=llm_allowed_rule_decisions_from_env(),
        intraday_limit_per_min=max(int(os.getenv("TAIL_BUY_INTRADAY_LIMIT_PER_MIN", "30")), 1),
        max_over_limit_symbols=max(min(int(os.getenv("TAIL_BUY_MAX_OVER_LIMIT_SYMBOLS", "5")), 5), 0),
        force_over_limit=env_flag("TAIL_BUY_FORCE_OVER_LIMIT", True),
        tickflow_task_retries=max(int(os.getenv("TAIL_BUY_TICKFLOW_MAX_RETRIES", "1")), 1),
        use_batch_intraday=env_flag("TAIL_BUY_USE_BATCH_INTRADAY", True),
        intraday_batch_size=max(min(int(os.getenv("TAIL_BUY_INTRADAY_BATCH_SIZE", "200")), 200), 1),
        holding_stop_config=holding_stop_config_from_env(),
        portfolio_id=str(args.portfolio_id or "USER_LIVE").strip() or "USER_LIVE",
        strategy_config=tail_buy_strategy_config_from_env(),
    )


def holding_stop_config_from_env() -> HoldingStopConfig:
    """持仓止损参数：固定百分比兜底 + 可选 ATR 波动率放宽（避免正常洗盘被误杀）。"""
    return HoldingStopConfig(
        hard_stop_pct=max(safe_float(os.getenv("TAIL_BUY_HOLDING_HARD_STOP_PCT", "12"), 12.0), 0.0),
        atr_enabled=env_flag("TAIL_BUY_HOLDING_ATR_STOP_ENABLED", False),
        atr_period=max(int(safe_float(os.getenv("TAIL_BUY_HOLDING_ATR_PERIOD", "14"), 14.0)), 2),
        atr_multiplier=max(safe_float(os.getenv("TAIL_BUY_HOLDING_ATR_MULTIPLIER", "2.0"), 2.0), 0.1),
        atr_max_relax_pct=max(safe_float(os.getenv("TAIL_BUY_HOLDING_ATR_MAX_RELAX_PCT", "15"), 15.0), 0.0),
    )


def default_tail_buy_logs_path(started_at: datetime) -> str:
    return os.path.join(
        os.getenv("LOGS_DIR", "logs"),
        f"tail_buy_1400_{started_at.strftime('%Y%m%d_%H%M%S')}.log",
    )


def llm_allowed_rule_decisions_from_env() -> tuple[str, ...]:
    values = [
        x.strip().upper()
        for x in str(os.getenv("TAIL_BUY_LLM_ALLOWED_RULE_DECISIONS", "BUY,WATCH") or "").split(",")
        if x.strip()
    ]
    return tuple(values) or (DECISION_BUY, DECISION_WATCH)


def _tail_buy_mode_from_args(args: Any) -> str:
    raw = str(getattr(args, "mode", "") or os.getenv("TAIL_BUY_MODE", "auto") or "auto").strip().lower()
    return raw if raw in {"auto", "intraday", "post_close_review"} else "auto"


def _append_optional_nvidia_route(routes: list[dict[str, str]], seen: set[tuple[str, str, str]]) -> None:
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    base_url = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip()
    model = os.getenv("NVIDIA_MODEL_KIMI", "").strip()
    if api_key and base_url and model:
        _append_route(routes, seen, f"nvidia-kimi:{model}", "openai", model, api_key, base_url)


def _append_route(
    routes: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    name: str,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = "",
) -> None:
    route = _route_payload(name, provider, model, api_key, base_url)
    if not route:
        return
    key = (route["provider"], route["model"], route["base_url"])
    if key in seen:
        return
    seen.add(key)
    routes.append(route)


def _route_payload(name: str, provider: str, model: str, api_key: str, base_url: str) -> dict[str, str] | None:
    provider_s = str(provider or "").strip().lower()
    model_s = str(model or "").strip()
    api_key_s = str(api_key or "").strip()
    base_url_s = str(base_url or "").strip()
    if not provider_s or not model_s or not api_key_s:
        return None
    return {"name": name, "provider": provider_s, "model": model_s, "api_key": api_key_s, "base_url": base_url_s}
