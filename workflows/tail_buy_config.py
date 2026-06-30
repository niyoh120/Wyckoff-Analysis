"""Runtime configuration loader for tail-buy strategy rules."""

from __future__ import annotations

import os

from core.tail_buy.models import safe_float
from core.tail_buy.strategy import TailBuyStrategyConfig

_TRUE_TEXTS = {"1", "true", "yes", "on"}


def tail_buy_strategy_config_from_env() -> TailBuyStrategyConfig:
    return TailBuyStrategyConfig(
        confirmed_only_buy=_env_bool("TAIL_BUY_CONFIRMED_ONLY_BUY", True),
        support_breach_tolerance_pct=max(_env_float("TAIL_BUY_SUPPORT_BREACH_TOLERANCE_PCT", 0.3), 0.0),
        blowoff_high_ret_pct=_env_float("TAIL_BUY_BLOWOFF_HIGH_RET_PCT", 5.0),
        blowoff_drop_from_high_pct=_env_float("TAIL_BUY_BLOWOFF_DROP_FROM_HIGH_PCT", 2.2),
        blowoff_close_pos_max=_env_float("TAIL_BUY_BLOWOFF_CLOSE_POS_MAX", 0.58),
        blowoff_tail_volume_share=_env_float("TAIL_BUY_BLOWOFF_TAIL_VOLUME_SHARE", 0.45),
        chase_day_ret_pct=_env_float("TAIL_BUY_CHASE_DAY_RET_PCT", 10.0),
        chase_high_ret_pct=_env_float("TAIL_BUY_CHASE_HIGH_RET_PCT", 12.0),
        weak_naked_day_ret_pct=_env_float("TAIL_BUY_WEAK_NAKED_DAY_RET_PCT", 0.8),
        weak_naked_tail30_ret_pct=_env_float("TAIL_BUY_WEAK_NAKED_TAIL30_RET_PCT", 0.3),
        naked_support_extension_pct=_env_float("TAIL_BUY_NAKED_SUPPORT_EXTENSION_PCT", 18.0),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_TEXTS


def _env_float(name: str, default: float) -> float:
    return safe_float(os.getenv(name), default)
