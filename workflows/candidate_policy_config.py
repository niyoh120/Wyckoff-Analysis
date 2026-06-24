"""Runtime configuration loader for candidate selection policy."""

from __future__ import annotations

import os

from core.candidate_policy import DEFAULT_POSITION_RATIO_BY_REGIME, CandidatePolicyConfig


def candidate_policy_config_from_env() -> CandidatePolicyConfig:
    evr_min_score = _env_optional_float("FUNNEL_LOSS_GUARD_PURE_EVR_MIN_SCORE")
    return CandidatePolicyConfig(
        loss_guard_enabled=_env_bool("FUNNEL_LOSS_GUARD_ENABLED", True),
        alpha_block_risk_on_early_breakout=_env_bool("FUNNEL_ALPHA_BLOCK_RISK_ON_EARLY_BREAKOUT", True),
        mix_trendpb_min_score=_env_float("FUNNEL_LOSS_GUARD_MIX_TRENDPB_MIN_SCORE", 12.0),
        pure_lps_min_score=_env_float("FUNNEL_LOSS_GUARD_PURE_LPS_MIN_SCORE", 6.0),
        pure_trendpb_min_score=_env_float("FUNNEL_LOSS_GUARD_PURE_TRENDPB_MIN_SCORE", 14.0),
        pure_sos_min_score=_env_float("FUNNEL_LOSS_GUARD_PURE_SOS_MIN_SCORE", 4.0),
        pure_evr_min_score_default=evr_min_score if evr_min_score is not None else 3.0,
        pure_evr_min_score_hot=evr_min_score if evr_min_score is not None else 5.0,
        risk_on_pre5_ret=_env_float("FUNNEL_LOSS_GUARD_RISK_ON_PRE5_RET", 25.0),
        risk_on_range_pos=_env_float("FUNNEL_LOSS_GUARD_RISK_ON_RANGE_POS", 85.0),
        risk_on_vol_ratio=_env_float("FUNNEL_LOSS_GUARD_RISK_ON_VOL_RATIO", 1.8),
        position_ratio_by_regime=_position_ratio_by_regime_from_env(),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _position_ratio_by_regime_from_env() -> dict[str, float]:
    ratios = dict(DEFAULT_POSITION_RATIO_BY_REGIME)
    for regime, default in DEFAULT_POSITION_RATIO_BY_REGIME.items():
        ratios[regime] = _position_ratio_from_env(regime, default)
    return ratios


def _position_ratio_from_env(regime: str, default: float) -> float:
    for prefix in ("FUNNEL_REGIME", "BACKTEST_REGIME"):
        raw = os.getenv(f"{prefix}_{regime}_POSITION_RATIO")
        if raw is None:
            continue
        try:
            return min(max(float(raw), 0.0), 1.0)
        except ValueError:
            return default
    return default
