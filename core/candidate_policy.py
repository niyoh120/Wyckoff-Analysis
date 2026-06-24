"""Shared candidate selection guardrails for live funnel and backtests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import pandas as pd

STRUCTURAL_L4_TRIGGERS = {"spring", "lps", "compression", "compress", "trend_pullback", "volatile_pullback"}
NAKED_RIGHT_SIDE_TRIGGERS = {"sos", "evr"}
DEFENSIVE_REGIMES = {"RISK_OFF", "BEAR_REBOUND", "PANIC_REPAIR", "CRASH", "BLACK_SWAN"}
WEAK_PULLBACK_REGIMES = DEFENSIVE_REGIMES | {"RISK_ON"}
DEFAULT_POSITION_RATIO_BY_REGIME: dict[str, float] = {
    "NEUTRAL": 0.5,
    "RISK_ON": 0.25,
    "BEAR_REBOUND": 0.0,
    "PANIC_REPAIR": 0.0,
    "RISK_OFF": 0.0,
    "CRASH": 0.0,
    "BLACK_SWAN": 0.0,
}


@dataclass(frozen=True)
class CandidatePolicyConfig:
    loss_guard_enabled: bool = True
    alpha_block_risk_on_early_breakout: bool = True
    alpha_risk_on_early_breakout_min_score: float = 70.0
    mix_trendpb_min_score: float = 12.0
    pure_lps_min_score: float = 6.0
    pure_trendpb_min_score: float = 14.0
    pure_sos_min_score: float = 4.0
    pure_evr_min_score_default: float = 3.0
    pure_evr_min_score_hot: float = 5.0
    risk_on_pre5_ret: float = 25.0
    risk_on_range_pos: float = 85.0
    risk_on_vol_ratio: float = 1.8
    defensive_high_range_pos: float = 78.0
    defensive_high_20d_ret: float = 18.0
    neutral_high_range_pos: float = 90.0
    neutral_high_20d_ret: float = 35.0
    position_ratio_by_regime: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_POSITION_RATIO_BY_REGIME)
    )

    def position_ratio(self, regime_norm: str) -> float:
        default = DEFAULT_POSITION_RATIO_BY_REGIME["NEUTRAL"]
        raw = self.position_ratio_by_regime.get(regime_norm, default)
        return min(max(float(raw), 0.0), 1.0)


DEFAULT_CANDIDATE_POLICY_CONFIG = CandidatePolicyConfig()


def _policy_config(config: CandidatePolicyConfig | None) -> CandidatePolicyConfig:
    return config or DEFAULT_CANDIDATE_POLICY_CONFIG


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


def apply_regime_position_filter(
    ranked_codes: list[str],
    regime: str,
    *,
    config: CandidatePolicyConfig | None = None,
) -> list[str]:
    if not ranked_codes:
        return []
    regime_norm = str(regime or "NEUTRAL").strip().upper() or "NEUTRAL"
    ratio = _policy_config(config).position_ratio(regime_norm)
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


def _recent_overheat(df: pd.DataFrame | None, config: CandidatePolicyConfig) -> bool:
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
        pre5_ret >= config.risk_on_pre5_ret
        and range_pos >= config.risk_on_range_pos
        and vol_ratio >= config.risk_on_vol_ratio
    )


def _recent_position_stats(df: pd.DataFrame | None) -> dict[str, float] | None:
    if df is None or df.empty or len(df) < 21:
        return None
    work = _numeric_ohlcv(df)
    if work is None:
        return None
    high20, low20 = float(work["high"].max()), float(work["low"].min())
    close = float(work.iloc[-1]["close"])
    base = float(work.iloc[0]["close"])
    range_pos = (close - low20) / (high20 - low20) * 100.0 if high20 > low20 else 0.0
    ret20 = (close / base - 1.0) * 100.0 if base > 0 else 0.0
    return {"range_pos": range_pos, "ret20": ret20}


def _late_stage_high_reason(
    regime_norm: str,
    keys: set[str],
    df: pd.DataFrame | None,
    config: CandidatePolicyConfig,
) -> str:
    if not keys or "spring" in keys or "volatile_pullback" in keys:
        return ""
    stats = _recent_position_stats(df)
    if not stats:
        return ""
    defensive = regime_norm in DEFENSIVE_REGIMES
    range_cut = config.defensive_high_range_pos if defensive else config.neutral_high_range_pos
    ret_cut = config.defensive_high_20d_ret if defensive else config.neutral_high_20d_ret
    if stats["range_pos"] >= range_cut and stats["ret20"] >= ret_cut:
        return f"{regime_norm}20日高位追涨"
    return ""


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
    *,
    config: CandidatePolicyConfig | None = None,
) -> str:
    policy = _policy_config(config)
    if not policy.loss_guard_enabled:
        return ""
    keys = _normalize_keys(trigger_keys)
    regime_norm = str(regime or "NEUTRAL").strip().upper() or "NEUTRAL"
    if keys == {"early_breakout"} and regime_norm == "RISK_ON":
        if policy.alpha_block_risk_on_early_breakout and trigger_score < policy.alpha_risk_on_early_breakout_min_score:
            return "RISK_ON低分早期突破"
    high_reason = _late_stage_high_reason(regime_norm, keys, df_map.get(code), policy)
    if high_reason:
        return high_reason
    if "lps" in keys and not (keys & {"sos", "evr", "spring"}):
        return _pure_lps_reason(regime_norm, trigger_score, policy)
    if keys == {"trend_pullback"}:
        return _pure_trend_pullback_reason(regime_norm, trigger_score, policy)
    if "trend_pullback" in keys and regime_norm in WEAK_PULLBACK_REGIMES:
        if trigger_score < policy.mix_trendpb_min_score:
            return f"{regime_norm}弱趋势回踩"
    if keys and keys <= NAKED_RIGHT_SIDE_TRIGGERS:
        reason = _naked_right_side_reason(regime_norm, keys, trigger_score, channel, df_map.get(code), policy)
        if reason:
            return reason
    return ""


def _pure_lps_reason(regime_norm: str, trigger_score: float, config: CandidatePolicyConfig) -> str:
    if trigger_score < config.pure_lps_min_score:
        return "低分LPS"
    if regime_norm in DEFENSIVE_REGIMES | {"RISK_ON"}:
        return f"{regime_norm}禁用LPS"
    return ""


def _pure_trend_pullback_reason(regime_norm: str, trigger_score: float, config: CandidatePolicyConfig) -> str:
    if trigger_score < config.pure_trendpb_min_score:
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
    config: CandidatePolicyConfig,
) -> str:
    if regime_norm in {"RISK_ON", "BEAR_REBOUND"} and _is_pure_momentum_channel(channel):
        return f"{regime_norm}纯趋势追涨"
    if "sos" in keys and trigger_score < config.pure_sos_min_score:
        return "低分SOS"
    evr_min_score = (
        config.pure_evr_min_score_hot
        if regime_norm in {"RISK_ON", "BEAR_REBOUND"}
        else config.pure_evr_min_score_default
    )
    if keys == {"evr"} and trigger_score < evr_min_score:
        return "低分EVR"
    if regime_norm in {"RISK_ON", "BEAR_REBOUND"} and _recent_overheat(df, config):
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
    config: CandidatePolicyConfig | None = None,
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
            config=config,
        )
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
        else:
            kept.append(code)
    kept_set = set(kept)
    return kept, [c for c in trend_selected if c in kept_set], [c for c in accum_selected if c in kept_set], dropped
