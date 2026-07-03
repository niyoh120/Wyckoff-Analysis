"""Runtime configuration loader for Step4 OMS workflow orchestration."""

from __future__ import annotations

from utils.env import env_bool as _env_bool
from utils.env import env_int as _env_int
from workflows.step4_models import NewBuyLimits, Step4RuntimeConfig


def step4_runtime_config_from_env() -> Step4RuntimeConfig:
    return Step4RuntimeConfig(
        trading_days=max(_env_int("STEP4_TRADING_DAYS", 320), 1),
        enforce_target_trade_date=_env_bool("STEP4_ENFORCE_TARGET_TRADE_DATE", False),
        max_output_tokens=max(_env_int("STEP4_MAX_OUTPUT_TOKENS", 8192), 1),
        atr_period=max(_env_int("STEP4_ATR_PERIOD", 14), 1),
        max_workers=max(_env_int("STEP4_MAX_WORKERS", 8), 1),
        max_external_report_candidates=max(_env_int("STEP4_MAX_EXTERNAL_REPORT_CANDIDATES", 12), 0),
        new_buy_limits=NewBuyLimits(
            risk_on=max(_env_int("STEP4_MAX_NEW_BUYS_RISK_ON", 2), 0),
            caution=max(_env_int("STEP4_MAX_NEW_BUYS_CAUTION", 1), 0),
            neutral=max(_env_int("STEP4_MAX_NEW_BUYS_NEUTRAL", 1), 0),
            risk_off=max(_env_int("STEP4_MAX_NEW_BUYS_RISK_OFF", 0), 0),
        ),
    )
