"""Runtime configuration loader for Step4 OMS workflow orchestration."""

from __future__ import annotations

import os

from utils.env import env_bool as _env_bool
from utils.env import env_int as _env_int
from workflows.step4_models import NewBuyLimits, Step4RuntimeConfig


def _ai_candidate_policy() -> str:
    policy = os.getenv("STEP4_AI_CANDIDATE_POLICY", "veto_only").strip().lower()
    return policy if policy in {"shadow", "veto_only"} else "veto_only"


def step4_runtime_config_from_env() -> Step4RuntimeConfig:
    return Step4RuntimeConfig(
        trading_days=max(_env_int("STEP4_TRADING_DAYS", 320), 1),
        enforce_target_trade_date=_env_bool("STEP4_ENFORCE_TARGET_TRADE_DATE", False),
        max_output_tokens=max(_env_int("STEP4_MAX_OUTPUT_TOKENS", 8192), 1),
        atr_period=max(_env_int("STEP4_ATR_PERIOD", 14), 1),
        max_workers=max(_env_int("STEP4_MAX_WORKERS", 8), 1),
        max_external_report_candidates=max(_env_int("STEP4_MAX_EXTERNAL_REPORT_CANDIDATES", 12), 0),
        ai_candidate_policy=_ai_candidate_policy(),
        new_buy_limits=NewBuyLimits(
            caution=min(max(_env_int("STEP4_MAX_NEW_BUYS_CAUTION", 1), 0), 1),
            neutral=max(_env_int("STEP4_MAX_NEW_BUYS_NEUTRAL", 1), 0),
        ),
    )
