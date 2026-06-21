"""Shared candidate selection guardrails for live funnel and backtests."""

from __future__ import annotations

import os
from collections.abc import Iterable

import pandas as pd

STRUCTURAL_L4_TRIGGERS = {"spring", "lps", "compression", "compress", "trend_pullback"}
NAKED_RIGHT_SIDE_TRIGGERS = {"sos", "evr"}
DEFENSIVE_REGIMES = {"RISK_OFF", "BEAR_REBOUND", "PANIC_REPAIR", "CRASH", "BLACK_SWAN"}
WEAK_PULLBACK_REGIMES = DEFENSIVE_REGIMES | {"RISK_ON"}
DEFAULT_POSITION_RATIO_BY_REGIME: dict[str, float] = {
    "NEUTRAL": 0.5,
    "RISK_ON": 0.25,
    "BEAR_REBOUND": 0.25,
    "PANIC_REPAIR": 0.0,
    "RISK_OFF": 0.0,
    "CRASH": 0.0,
    "BLACK_SWAN": 0.0,
}


def _env_bool(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _position_ratio_for_regime(regime_norm: str) -> float:
    default = DEFAULT_POSITION_RATIO_BY_REGIME.get(regime_norm, DEFAULT_POSITION_RATIO_BY_REGIME["NEUTRAL"])
    for prefix in ("FUNNEL_REGIME", "BACKTEST_REGIME"):
        raw = os.getenv(f"{prefix}_{regime_norm}_POSITION_RATIO")
        if raw is None:
            continue
        try:
            return min(max(float(raw), 0.0), 1.0)
        except ValueError:
            return default
    return default


def trigger_sets_by_code(triggers: dict[str, list[tuple[str, float]]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for trigger, pairs in (triggers or {}).items():
        key = str(trigger).strip().lower()
        if not key:
            continue
        for code, _score in pairs or []:
            code_s = str(code).strip()
            if code_s:
                out.setdefault(code_s, set()).add(key)
    return out


def is_tradeable_l4_trigger_combo(trigger_keys: Iterable[str]) -> bool:
    keys = _normalize_keys(trigger_keys)
    if not keys:
        return False
    if keys & STRUCTURAL_L4_TRIGGERS:
        return True
    return not keys <= NAKED_RIGHT_SIDE_TRIGGERS


def apply_regime_position_filter(ranked_codes: list[str], regime: str) -> list[str]:
    if not ranked_codes:
        return []
    regime_norm = str(regime or "NEUTRAL").strip().upper() or "NEUTRAL"
    ratio = _position_ratio_for_regime(regime_norm)
    if ratio <= 0:
        return []
    if ratio >= 1.0:
        return ranked_codes
    keep_n = max(1, int(len(ranked_codes) * ratio + 0.5))
    return ranked_codes[:keep_n]


def rerank_selected_codes(codes: list[str], score_map: dict[str, float]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for code in codes:
        code_s = str(code).strip()
        if code_s and code_s not in seen:
            deduped.append(code_s)
            seen.add(code_s)
    return sorted(deduped, key=lambda c: (-float(score_map.get(c, 0.0) or 0.0), c))


def _normalize_keys(trigger_keys: Iterable[str]) -> set[str]:
    return {str(k).strip().lower() for k in trigger_keys if str(k).strip()}


def _channel_tags(raw: str) -> set[str]:
    return {x.strip() for x in str(raw or "").split("+") if x.strip()}


def _is_pure_momentum_channel(channel: str) -> bool:
    tags = _channel_tags(channel)
    if not tags or "点火破局" in tags:
        return False
    return bool(tags <= {"主升通道", "趋势延续", "加速突破"})


def _recent_overheat(df: pd.DataFrame | None) -> bool:
    if df is None or df.empty or len(df) < 21:
        return False
    work = _numeric_ohlcv(df)
    if work is None:
        return False
    high20, low20 = float(work["high"].max()), float(work["low"].min())
    close = float(work.iloc[-1]["close"])
    pre5_ret = (close / float(work.iloc[-6]["close"]) - 1.0) * 100.0
    range_pos = (close - low20) / (high20 - low20) * 100.0 if high20 > low20 else 0.0
    vol20 = float(work["volume"].tail(20).mean())
    vol_ratio = float(work["volume"].tail(5).mean()) / vol20 if vol20 > 0 else 0.0
    return (
        pre5_ret >= _env_float("FUNNEL_LOSS_GUARD_RISK_ON_PRE5_RET", "25.0")
        and range_pos >= _env_float("FUNNEL_LOSS_GUARD_RISK_ON_RANGE_POS", "85.0")
        and vol_ratio >= _env_float("FUNNEL_LOSS_GUARD_RISK_ON_VOL_RATIO", "1.8")
    )


def _numeric_ohlcv(df: pd.DataFrame) -> pd.DataFrame | None:
    work = df.copy()
    for col in ("close", "high", "low", "volume"):
        if col not in work.columns:
            return None
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.tail(21).dropna(subset=["close", "high", "low", "volume"])
    return work if len(work) >= 21 and float(work.iloc[-1]["close"]) > 0 else None


def loss_guard_reason(
    code: str,
    regime: str,
    trigger_keys: Iterable[str],
    trigger_score: float,
    channel: str,
    df_map: dict[str, pd.DataFrame],
) -> str:
    if not _env_bool("FUNNEL_LOSS_GUARD_ENABLED", "1"):
        return ""
    keys = _normalize_keys(trigger_keys)
    regime_norm = str(regime or "NEUTRAL").strip().upper() or "NEUTRAL"
    if keys == {"early_breakout"} and regime_norm == "RISK_ON":
        if _env_bool("FUNNEL_ALPHA_BLOCK_RISK_ON_EARLY_BREAKOUT", "1"):
            return "RISK_ON禁用早期突破"
    if "lps" in keys and not (keys & {"sos", "evr", "spring"}):
        return _pure_lps_reason(regime_norm, trigger_score)
    if keys == {"trend_pullback"}:
        return _pure_trend_pullback_reason(regime_norm, trigger_score)
    if "trend_pullback" in keys and regime_norm in WEAK_PULLBACK_REGIMES:
        if trigger_score < _env_float("FUNNEL_LOSS_GUARD_MIX_TRENDPB_MIN_SCORE", "12.0"):
            return f"{regime_norm}弱趋势回踩"
    if keys and keys <= NAKED_RIGHT_SIDE_TRIGGERS:
        reason = _naked_right_side_reason(regime_norm, keys, trigger_score, channel, df_map.get(code))
        if reason:
            return reason
    return ""


def _pure_lps_reason(regime_norm: str, trigger_score: float) -> str:
    if trigger_score < _env_float("FUNNEL_LOSS_GUARD_PURE_LPS_MIN_SCORE", "6.0"):
        return "低分LPS"
    if regime_norm in DEFENSIVE_REGIMES | {"RISK_ON"}:
        return f"{regime_norm}禁用LPS"
    return ""


def _pure_trend_pullback_reason(regime_norm: str, trigger_score: float) -> str:
    if trigger_score < _env_float("FUNNEL_LOSS_GUARD_PURE_TRENDPB_MIN_SCORE", "14.0"):
        return "低分TrendPB"
    if regime_norm in WEAK_PULLBACK_REGIMES:
        return f"{regime_norm}禁用TrendPB"
    return ""


def _naked_right_side_reason(
    regime_norm: str,
    keys: set[str],
    trigger_score: float,
    channel: str,
    df: pd.DataFrame | None,
) -> str:
    if regime_norm in {"RISK_ON", "BEAR_REBOUND"} and _is_pure_momentum_channel(channel):
        return f"{regime_norm}纯趋势追涨"
    if "sos" in keys and trigger_score < _env_float("FUNNEL_LOSS_GUARD_PURE_SOS_MIN_SCORE", "4.0"):
        return "低分SOS"
    evr_min_score = "5.0" if regime_norm in {"RISK_ON", "BEAR_REBOUND"} else "3.0"
    if keys == {"evr"} and trigger_score < _env_float("FUNNEL_LOSS_GUARD_PURE_EVR_MIN_SCORE", evr_min_score):
        return "低分EVR"
    if regime_norm in {"RISK_ON", "BEAR_REBOUND"} and _recent_overheat(df):
        return f"{regime_norm}短期过热"
    return ""


def apply_loss_guard(
    selected_for_ai: list[str],
    trend_selected: list[str],
    accum_selected: list[str],
    *,
    regime: str,
    code_to_trigger_keys: dict[str, Iterable[str]],
    code_to_total_score: dict[str, float],
    channel_map: dict[str, str],
    df_map: dict[str, pd.DataFrame],
) -> tuple[list[str], list[str], list[str], dict[str, int]]:
    kept: list[str] = []
    dropped: dict[str, int] = {}
    for code in selected_for_ai:
        reason = loss_guard_reason(
            code,
            regime,
            code_to_trigger_keys.get(code, []),
            float(code_to_total_score.get(code, 0.0) or 0.0),
            str(channel_map.get(code, "") or ""),
            df_map,
        )
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
        else:
            kept.append(code)
    kept_set = set(kept)
    return kept, [c for c in trend_selected if c in kept_set], [c for c in accum_selected if c in kept_set], dropped
