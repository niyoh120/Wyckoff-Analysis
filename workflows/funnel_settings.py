"""Runtime settings for the Wyckoff funnel job."""

from __future__ import annotations

import os

TRUE_VALUES = {"1", "true", "yes", "on"}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUE_VALUES


def _int_env(name: str, default: int, *, min_value: int | None = None) -> int:
    try:
        value = int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        value = default
    return max(value, min_value) if min_value is not None else value


def _float_env(name: str, default: float, *, min_value: float | None = None) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(value, min_value) if min_value is not None else value


TRADING_DAYS = _int_env("FUNNEL_TRADING_DAYS", 320)
BATCH_TIMEOUT = _int_env("FUNNEL_BATCH_TIMEOUT", 420)
BATCH_SIZE = _int_env("FUNNEL_BATCH_SIZE", 200)
BATCH_SLEEP = _float_env("FUNNEL_BATCH_SLEEP", 0.55)
MAX_WORKERS = _int_env("FUNNEL_MAX_WORKERS", 8)
EXECUTOR_MODE = os.getenv("FUNNEL_EXECUTOR_MODE", "process").strip().lower()
if EXECUTOR_MODE not in {"thread", "process"}:
    EXECUTOR_MODE = "process"

BREADTH_MA_WINDOW = _int_env("FUNNEL_BREADTH_MA_WINDOW", 20)
SMALLCAP_BENCH_CODE = os.getenv("FUNNEL_SMALLCAP_BENCH_CODE", "399006").strip() or "399006"

FUNNEL_EXPORT_FULL_FETCH = _bool_env("FUNNEL_EXPORT_FULL_FETCH", False)
FUNNEL_EXPORT_DIR = os.getenv("FUNNEL_EXPORT_DIR", "data/funnel_snapshots").strip() or "data/funnel_snapshots"
FUNNEL_AI_SELECTION_MODE = os.getenv("FUNNEL_AI_SELECTION_MODE", "tradeable_l4").strip().lower()
FUNNEL_FULL_FORMAL_L4_MAX = _int_env("FUNNEL_FULL_FORMAL_L4_MAX", 25, min_value=0)
FUNNEL_DEFENSIVE_FORCE_QUOTA = _bool_env("FUNNEL_DEFENSIVE_FORCE_QUOTA", True)
FUNNEL_CARD_STYLE = os.getenv("FUNNEL_CARD_STYLE", "legacy_compact").strip().lower()
FUNNEL_BYPASS_DISPLAY_LIMIT = _int_env("FUNNEL_BYPASS_DISPLAY_LIMIT", 20, min_value=0)
FUNNEL_LEADER_RADAR_DISPLAY_LIMIT = _int_env("FUNNEL_LEADER_RADAR_DISPLAY_LIMIT", 20, min_value=0)
FUNNEL_L2_BYPASS_AI_ENABLED = _bool_env("FUNNEL_L2_BYPASS_AI_ENABLED", False)
FUNNEL_L2_BYPASS_AI_CAP = _int_env("FUNNEL_L2_BYPASS_AI_CAP", 30, min_value=0)
FUNNEL_ETF_DISPLAY_LIMIT = _int_env("FUNNEL_ETF_DISPLAY_LIMIT", 0, min_value=0)

FUNNEL_THEME_RADAR_ENABLED = _bool_env("FUNNEL_THEME_RADAR_ENABLED", True)
FUNNEL_THEME_RADAR_LINK_ENABLED = _bool_env("FUNNEL_THEME_RADAR_LINK_ENABLED", True)
FUNNEL_THEME_RADAR_PROMOTE_CAP = _int_env("FUNNEL_THEME_RADAR_PROMOTE_CAP", 6, min_value=0)
FUNNEL_THEME_RADAR_BONUS_MAX = _float_env("FUNNEL_THEME_RADAR_BONUS_MAX", 18.0, min_value=0.0)
FUNNEL_THEME_RADAR_MAX_AGE_DAYS = _int_env("FUNNEL_THEME_RADAR_MAX_AGE_DAYS", 14, min_value=0)

FUNNEL_MAINLINE_ENGINE_ENABLED = _bool_env("FUNNEL_MAINLINE_ENGINE_ENABLED", True)
FUNNEL_MAINLINE_MAX_AI_CANDIDATES = _int_env("FUNNEL_MAINLINE_MAX_AI_CANDIDATES", 3, min_value=0)
FUNNEL_MAINLINE_MIN_THEME_SCORE = _float_env("FUNNEL_MAINLINE_MIN_THEME_SCORE", 0.55, min_value=0.0)
FUNNEL_MAINLINE_MIN_STOCK_SCORE = _float_env("FUNNEL_MAINLINE_MIN_STOCK_SCORE", 0.60, min_value=0.0)
FUNNEL_MAINLINE_MIN_TIMING_SCORE = _float_env("FUNNEL_MAINLINE_MIN_TIMING_SCORE", 0.55, min_value=0.0)
FUNNEL_MAINLINE_ALLOW_L2_BYPASS = _bool_env("FUNNEL_MAINLINE_ALLOW_L2_BYPASS", True)
FUNNEL_MAINLINE_ALLOW_L4_BYPASS = _bool_env("FUNNEL_MAINLINE_ALLOW_L4_BYPASS", False)
FUNNEL_MAINLINE_DISPLAY_LIMIT = _int_env("FUNNEL_MAINLINE_DISPLAY_LIMIT", 8, min_value=0)

FUNNEL_STRATEGIC_L2_BYPASS_ENABLED = _bool_env("FUNNEL_STRATEGIC_L2_BYPASS_ENABLED", True)
FUNNEL_STRATEGIC_L2_BYPASS_AI_ENABLED = _bool_env("FUNNEL_STRATEGIC_L2_BYPASS_AI_ENABLED", False)
FUNNEL_STRATEGIC_L2_BYPASS_AI_CAP = _int_env("FUNNEL_STRATEGIC_L2_BYPASS_AI_CAP", 12, min_value=0)
FUNNEL_STRATEGIC_L2_BYPASS_MIN_THEME_SCORE = _float_env(
    "FUNNEL_STRATEGIC_L2_BYPASS_MIN_THEME_SCORE",
    0.45,
    min_value=0.0,
)
FUNNEL_STRATEGIC_L2_BYPASS_MIN_STOCK_SCORE = _float_env(
    "FUNNEL_STRATEGIC_L2_BYPASS_MIN_STOCK_SCORE",
    0.55,
    min_value=0.0,
)
FUNNEL_STRATEGIC_L2_BYPASS_RESCUE_ENABLED = _bool_env("FUNNEL_STRATEGIC_L2_BYPASS_RESCUE_ENABLED", True)
FUNNEL_STRATEGIC_L2_BYPASS_RESCUE_MIN_SCORE = _float_env(
    "FUNNEL_STRATEGIC_L2_BYPASS_RESCUE_MIN_SCORE",
    55.0,
    min_value=0.0,
)
