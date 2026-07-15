"""Runtime configuration loader for AI candidate allocation."""

from __future__ import annotations

import os

from core.ai_candidate_allocation import DEFAULT_AI_QUOTA_BY_FAMILY, AiCandidateAllocationConfig


def ai_candidate_allocation_config_from_env() -> AiCandidateAllocationConfig:
    return AiCandidateAllocationConfig(
        total_cap=_env_non_negative_int("FUNNEL_AI_TOTAL_CAP", 8),
        max_per_sector=_env_non_negative_int("FUNNEL_AI_MAX_PER_SECTOR", 2),
        max_trend_l3_fill=_env_non_negative_int("FUNNEL_AI_MAX_TREND_L3_FILL", 0),
        max_accum_l3_fill=_env_non_negative_int("FUNNEL_AI_MAX_ACCUM_L3_FILL", 0),
        quota_by_family={
            "RISK_ON": (
                _env_non_negative_int("FUNNEL_AI_RISK_ON_TREND", DEFAULT_AI_QUOTA_BY_FAMILY["RISK_ON"][0]),
                _env_non_negative_int("FUNNEL_AI_RISK_ON_ACCUM", DEFAULT_AI_QUOTA_BY_FAMILY["RISK_ON"][1]),
            ),
            "BEAR_REBOUND": (
                _env_non_negative_int(
                    "FUNNEL_AI_BEAR_REBOUND_TREND",
                    DEFAULT_AI_QUOTA_BY_FAMILY["BEAR_REBOUND"][0],
                ),
                _env_non_negative_int(
                    "FUNNEL_AI_BEAR_REBOUND_ACCUM",
                    DEFAULT_AI_QUOTA_BY_FAMILY["BEAR_REBOUND"][1],
                ),
            ),
            "RISK_OFF": (
                _env_non_negative_int("FUNNEL_AI_RISK_OFF_TREND", DEFAULT_AI_QUOTA_BY_FAMILY["RISK_OFF"][0]),
                _env_non_negative_int("FUNNEL_AI_RISK_OFF_ACCUM", DEFAULT_AI_QUOTA_BY_FAMILY["RISK_OFF"][1]),
            ),
            "NEUTRAL": (
                _env_non_negative_int("FUNNEL_AI_NEUTRAL_TREND", DEFAULT_AI_QUOTA_BY_FAMILY["NEUTRAL"][0]),
                _env_non_negative_int("FUNNEL_AI_NEUTRAL_ACCUM", DEFAULT_AI_QUOTA_BY_FAMILY["NEUTRAL"][1]),
            ),
        },
    )


def _env_non_negative_int(name: str, default: int) -> int:
    try:
        return max(int(float(os.getenv(name, str(default)))), 0)
    except (TypeError, ValueError):
        return default
