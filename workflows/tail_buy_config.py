"""Runtime configuration loader for tail-buy strategy rules."""

from __future__ import annotations

import os

from core.tail_buy.strategy import TailBuyStrategyConfig
from utils.env import env_bool as _env_bool
from utils.env import env_float as _env_float


def tail_buy_strategy_config_from_env() -> TailBuyStrategyConfig:
    ai_policy = os.getenv("TAIL_BUY_AI_POLICY", "veto_only").strip().lower()
    if ai_policy not in {"shadow", "veto_only"}:
        ai_policy = "veto_only"
    return TailBuyStrategyConfig(
        confirmed_only_buy=_env_bool("TAIL_BUY_CONFIRMED_ONLY_BUY", True),
        ai_policy=ai_policy,
        support_breach_tolerance_pct=max(_env_float("TAIL_BUY_SUPPORT_BREACH_TOLERANCE_PCT", 0.3), 0.0),
        blowoff_high_ret_pct=_env_float("TAIL_BUY_BLOWOFF_HIGH_RET_PCT", 5.0),
        blowoff_drop_from_high_pct=_env_float("TAIL_BUY_BLOWOFF_DROP_FROM_HIGH_PCT", 2.2),
        blowoff_close_pos_max=_env_float("TAIL_BUY_BLOWOFF_CLOSE_POS_MAX", 0.58),
        blowoff_tail_volume_share=_env_float("TAIL_BUY_BLOWOFF_TAIL_VOLUME_SHARE", 0.45),
        chase_day_ret_pct=_env_float("TAIL_BUY_CHASE_DAY_RET_PCT", 7.0),
        chase_high_ret_pct=_env_float("TAIL_BUY_CHASE_HIGH_RET_PCT", 9.0),
        weak_naked_day_ret_pct=_env_float("TAIL_BUY_WEAK_NAKED_DAY_RET_PCT", 0.8),
        weak_naked_tail30_ret_pct=_env_float("TAIL_BUY_WEAK_NAKED_TAIL30_RET_PCT", 0.3),
        naked_support_extension_pct=_env_float("TAIL_BUY_NAKED_SUPPORT_EXTENSION_PCT", 18.0),
        daily_trap_gate_enabled=_env_bool("TAIL_BUY_DAILY_TRAP_GATE_ENABLED", True),
        daily_trap_ma20_extension_pct=_env_float("TAIL_BUY_DAILY_TRAP_MA20_EXTENSION_PCT", 18.0),
        daily_trap_upper_shadow_pct=_env_float("TAIL_BUY_DAILY_TRAP_UPPER_SHADOW_PCT", 4.0),
        daily_trap_volume_ratio=_env_float("TAIL_BUY_DAILY_TRAP_VOLUME_RATIO", 1.8),
        left_probe_close_pos_min=min(max(_env_float("TAIL_BUY_LEFT_PROBE_CLOSE_POS_MIN", 0.65), 0.0), 1.0),
        left_probe_spring_quality_min=min(max(_env_float("TAIL_BUY_LEFT_PROBE_SPRING_QUALITY_MIN", 50.0), 0.0), 100.0),
    )
