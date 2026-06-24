"""Runtime configuration loader for Step4 OMS workflow orchestration."""

from __future__ import annotations

import os

from workflows.step4_models import NewBuyLimits, Step4RuntimeConfig

_TRUE_TEXTS = {"1", "true", "yes", "on"}


def step4_runtime_config_from_env() -> Step4RuntimeConfig:
    return Step4RuntimeConfig(
        trading_days=max(_env_int("STEP4_TRADING_DAYS", 320), 1),
        enforce_target_trade_date=_env_bool("STEP4_ENFORCE_TARGET_TRADE_DATE", False),
        max_output_tokens=max(_env_int("STEP4_MAX_OUTPUT_TOKENS", 8192), 1),
        atr_period=max(_env_int("STEP4_ATR_PERIOD", 14), 1),
        max_workers=max(_env_int("STEP4_MAX_WORKERS", 8), 1),
        new_buy_limits=NewBuyLimits(
            risk_on=max(_env_int("STEP4_MAX_NEW_BUYS_RISK_ON", 2), 0),
            caution=max(_env_int("STEP4_MAX_NEW_BUYS_CAUTION", 1), 0),
            neutral=max(_env_int("STEP4_MAX_NEW_BUYS_NEUTRAL", 1), 0),
            risk_off=max(_env_int("STEP4_MAX_NEW_BUYS_RISK_OFF", 0), 0),
        ),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_TEXTS


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default
