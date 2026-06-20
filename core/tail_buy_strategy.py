"""
尾盘买入策略核心（规则层 + LLM 合并层）。
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.intraday_analysis import (
    compute_effort_vs_result,
    compute_smart_money_score,
    compute_spring_quality,
    compute_vol_price_corr,
    ensure_intraday_df,
    infer_session_vwap,
)

logger = logging.getLogger(__name__)
DECISION_BUY = "BUY"
DECISION_WATCH = "WATCH"
DECISION_SKIP = "SKIP"
VALID_DECISIONS = {DECISION_BUY, DECISION_WATCH, DECISION_SKIP}
_TRUE_TEXTS = {"1", "true", "yes", "on"}


@dataclass
class TailBuyCandidate:
    code: str
    name: str
    signal_date: str
    status: str
    signal_type: str
    signal_score: float
    snap: dict[str, Any] = field(default_factory=dict)
    rule_score: float = 0.0
    rule_decision: str = DECISION_SKIP
    rule_reasons: list[str] = field(default_factory=list)
    llm_decision: str | None = None
    llm_reason: str = ""
    llm_confidence: float | None = None
    llm_model_used: str = ""
    final_decision: str = DECISION_SKIP
    priority_score: float = 0.0
    fetch_error: str = ""
    features: dict[str, Any] = field(default_factory=dict)
    summary_5m: str = ""


def normalize_cn_code(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "").strip() if ch.isdigit())
    if not digits:
        return ""
    if len(digits) > 6:
        digits = digits[-6:]
    return digits.zfill(6)


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        if raw is None:
            return default
        text = str(raw).strip()
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    return _safe_float(os.getenv(name), default)


def _infer_session_vwap(close: pd.Series, total_volume: float, total_amount: float) -> tuple[float, float]:
    return infer_session_vwap(close, total_volume, total_amount)


def _normalize_status(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    return text if text else "pending"


def _confirmed_only_buy_enabled() -> bool:
    return os.getenv("TAIL_BUY_CONFIRMED_ONLY_BUY", "1").strip().lower() in _TRUE_TEXTS


def _apply_unconfirmed_buy_gate(candidate: TailBuyCandidate) -> TailBuyCandidate:
    if not _confirmed_only_buy_enabled() or _normalize_status(candidate.status) == "confirmed":
        return candidate
    if candidate.rule_decision == DECISION_BUY:
        candidate.rule_decision = DECISION_WATCH
        candidate.rule_reasons.append("未二次确认，尾盘只观察不买入")
    if candidate.final_decision == DECISION_BUY:
        candidate.final_decision = DECISION_WATCH
        candidate.llm_reason = (
            f"{candidate.llm_reason}；未二次确认，降级观察" if candidate.llm_reason else "未二次确认，降级观察"
        )
    if candidate.final_decision == DECISION_WATCH:
        candidate.priority_score = candidate.rule_score + 3.0
    return candidate


def _normalize_signal_date(raw: Any) -> str:
    text = str(raw or "").strip()
    if len(text) >= 10:
        return text[:10]
    return text


def pick_tail_candidates(
    rows: list[dict[str, Any]],
    *,
    cutoff_date: str,
    statuses: tuple[str, ...] = ("pending", "confirmed"),
) -> list[TailBuyCandidate]:
    """从 signal_pending 原始行中过滤候选：
    - signal_date >= cutoff_date
    - status in statuses
    - 同代码只保留更优记录（confirmed > pending；日期更新优先；分数更高优先）
    """
    allowed = {str(x).strip().lower() for x in statuses}
    cutoff = _normalize_signal_date(cutoff_date)
    by_code: dict[str, TailBuyCandidate] = {}

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        signal_date = _normalize_signal_date(row.get("signal_date"))
        if signal_date < cutoff:
            continue
        status = _normalize_status(row.get("status"))
        if status not in allowed:
            continue
        code = normalize_cn_code(row.get("code"))
        if not code:
            continue
        candidate = TailBuyCandidate(
            code=code,
            name=str(row.get("name", "") or code).strip() or code,
            signal_date=signal_date,
            status=status,
            signal_type=str(row.get("signal_type", "") or "").strip() or "unknown",
            signal_score=_safe_float(row.get("signal_score"), 0.0),
            snap={k: v for k, v in row.items() if k.startswith("snap_")},
        )
        old = by_code.get(code)
        if old is None:
            by_code[code] = candidate
            continue
        old_rank = (1 if old.status == "confirmed" else 0, old.signal_date)
        new_rank = (1 if candidate.status == "confirmed" else 0, candidate.signal_date)
        if (new_rank, candidate.signal_score) > (old_rank, old.signal_score):
            by_code[code] = candidate

    out = list(by_code.values())
    out.sort(key=lambda x: (x.status != "confirmed", -x.signal_score, x.code))
    return out


def _ensure_intraday_df(df: pd.DataFrame) -> pd.DataFrame:
    return ensure_intraday_df(df)


def _support_guard_features(
    *,
    last_close: float,
    day_low: float,
    daily_context: dict[str, Any] | None,
) -> dict[str, Any]:
    support = _safe_float((daily_context or {}).get("support_level"), 0.0)
    if support <= 0:
        return {
            "support_level": 0.0,
            "close_vs_support_pct": 0.0,
            "day_low_vs_support_pct": 0.0,
            "close_below_support": False,
            "day_low_breached_support": False,
        }
    tolerance_pct = max(_env_float("TAIL_BUY_SUPPORT_BREACH_TOLERANCE_PCT", 0.3), 0.0)
    support_floor = support * (1.0 - tolerance_pct / 100.0)
    return {
        "support_level": support,
        "close_vs_support_pct": (last_close / support - 1.0) * 100.0,
        "day_low_vs_support_pct": (day_low / support - 1.0) * 100.0,
        "close_below_support": bool(last_close < support_floor),
        "day_low_breached_support": bool(day_low < support_floor),
    }


def _is_tail_blowoff_reversal(features: dict[str, Any]) -> bool:
    high_ret = _safe_float(features.get("intraday_high_ret_pct"), 0.0)
    drop = _safe_float(features.get("drop_from_high_pct"), 0.0)
    close_pos = _safe_float(features.get("close_pos"), 0.0)
    tail_share = _safe_float(features.get("tail30_volume_share"), 0.0)
    return (
        high_ret >= _env_float("TAIL_BUY_BLOWOFF_HIGH_RET_PCT", 5.0)
        and drop <= -abs(_env_float("TAIL_BUY_BLOWOFF_DROP_FROM_HIGH_PCT", 2.2))
        and close_pos <= _env_float("TAIL_BUY_BLOWOFF_CLOSE_POS_MAX", 0.58)
        and tail_share >= _env_float("TAIL_BUY_BLOWOFF_TAIL_VOLUME_SHARE", 0.45)
    )


def _tail_hard_veto_reasons(features: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    support = _safe_float(features.get("support_level"), 0.0)
    if support > 0 and bool(features.get("day_low_breached_support")):
        reasons.append(f"当天跌破确认支撑{support:.2f}，尾盘不买")
    elif support > 0 and bool(features.get("close_below_support")):
        reasons.append(f"尾盘收在确认支撑{support:.2f}下方")
    if bool(features.get("tail_blowoff_reversal")):
        reasons.append("极端放量冲高回落，疑似派发")
    return reasons


def _ret_pct(series: pd.Series, lookback: int) -> float:
    if len(series) <= lookback:
        return 0.0
    base = _safe_float(series.iloc[-(lookback + 1)], 0.0)
    now = _safe_float(series.iloc[-1], 0.0)
    return 0.0 if base <= 0 else (now / base - 1.0) * 100.0


def _tail_volume_share(volume: pd.Series, total_volume: float, lookback: int) -> float:
    return float(volume.tail(min(lookback, len(volume))).sum()) / total_volume if total_volume > 0 else 0.0


def _reclaim_vwap(close: pd.Series, *, last_close: float, vwap: float) -> bool:
    history_window = min(90, max(len(close) - 1, 1))
    history_before_tail = close.iloc[: -min(20, len(close))] if len(close) > 20 else close.iloc[:-1]
    if history_before_tail.empty:
        history_before_tail = close.iloc[:-1]
    min_before_tail = _safe_float(history_before_tail.tail(history_window).min(), last_close)
    return bool(last_close >= vwap * 1.001 and min_before_tail < vwap * 0.998)


def _strong_hold_vwap_ratio(
    close: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    amount: pd.Series,
    volume_scale: float,
) -> float:
    if len(close) < 60:
        return 0.0
    scaled_volume = (volume.fillna(0.0) * max(volume_scale, 1e-9)).clip(lower=0.0)
    cum_vol = scaled_volume.cumsum()
    dynamic_vwap = amount.fillna(0.0).cumsum() / cum_vol.replace(0.0, pd.NA)
    valid = dynamic_vwap.dropna()
    if valid.empty:
        return 0.0
    start = min(max(len(close) // 6, 15), 40)
    close_tail = close.iloc[start:]
    low_tail = low.iloc[start:]
    vwap_tail = dynamic_vwap.iloc[start:]
    if close_tail.empty:
        return 0.0
    close_above = close_tail >= vwap_tail * 0.998
    low_breach = low_tail < vwap_tail * 0.993
    return float(close_above.mean() - low_breach.mean() * 0.5)


def _breakout_tail(high: pd.Series, *, last_close: float, day_high: float) -> bool:
    if len(high) <= 35:
        return bool(last_close >= day_high * 0.98)
    prev_peak = _safe_float(high.iloc[:-30].max(), day_high)
    return bool(last_close >= prev_peak * 0.998)


def _slope_pct(close: pd.Series, lookback: int) -> float:
    if len(close) < lookback:
        return 0.0
    base = _safe_float(close.iloc[-lookback], 0.0)
    return 0.0 if base <= 0 else (_safe_float(close.iloc[-1], 0.0) / base - 1.0) * 100.0


def _base_tail_features(df: pd.DataFrame) -> dict[str, Any]:
    close = df["close"].ffill()
    high = df["high"].fillna(close)
    low = df["low"].fillna(close)
    volume = df["volume"].fillna(0.0)
    amount = df["amount"].fillna(close * volume)
    first_open = _safe_float(df["open"].iloc[0] if "open" in df.columns else close.iloc[0], close.iloc[0])
    last_close = _safe_float(close.iloc[-1], 0.0)
    day_high = _safe_float(high.max(), last_close)
    day_low = _safe_float(low.min(), last_close)
    total_volume = float(volume.sum())
    vwap, vwap_volume_scale = _infer_session_vwap(close, total_volume, float(amount.sum()))
    day_range = max(day_high - day_low, 1e-8)
    close_pos = max(0.0, min(1.0, (last_close - day_low) / day_range))
    day_ret_pct = ((last_close / first_open - 1.0) * 100.0) if first_open > 0 else 0.0
    drop_from_high_pct = (last_close / day_high - 1.0) * 100.0 if day_high > 0 else 0.0
    hold_vwap_ratio = _strong_hold_vwap_ratio(close, low, volume, amount, vwap_volume_scale)
    strong_hold_vwap = (
        hold_vwap_ratio >= 0.82 and close_pos >= 0.72 and day_ret_pct >= 0.5 and drop_from_high_pct >= -1.8
    )
    return {
        "bars": int(len(df)),
        "last_close": last_close,
        "first_open": first_open,
        "day_high": day_high,
        "day_low": day_low,
        "vwap": vwap,
        "vwap_volume_scale": vwap_volume_scale,
        "close_pos": close_pos,
        "day_ret_pct": day_ret_pct,
        "intraday_high_ret_pct": ((day_high / first_open - 1.0) * 100.0) if first_open > 0 else 0.0,
        "last30_ret_pct": _ret_pct(close, 30),
        "last15_ret_pct": _ret_pct(close, 15),
        "tail30_volume_share": _tail_volume_share(volume, total_volume, 30),
        "tail15_volume_share": _tail_volume_share(volume, total_volume, 15),
        "drop_from_high_pct": drop_from_high_pct,
        "dist_vwap_pct": (last_close / vwap - 1.0) * 100.0 if vwap > 0 else 0.0,
        "hold_vwap_ratio": hold_vwap_ratio,
        "strong_hold_vwap": bool(strong_hold_vwap),
        "reclaim_vwap": _reclaim_vwap(close, last_close=last_close, vwap=vwap),
        "breakout_tail": _breakout_tail(high, last_close=last_close, day_high=day_high),
        "slope_10_pct": _slope_pct(close, 10),
    }


def compute_tail_features(df_1m: pd.DataFrame, daily_context: dict[str, Any] | None = None) -> dict[str, Any]:
    df = _ensure_intraday_df(df_1m)
    if df.empty:
        return {"bars": 0}

    features = _base_tail_features(df)
    features.update(
        {
            "vol_price_corr": compute_vol_price_corr(df),
            "effort_vs_result": compute_effort_vs_result(df),
            "smart_money_score": compute_smart_money_score(df),
            "spring_quality": compute_spring_quality(df, daily_context) if daily_context else None,
        }
    )
    features.update(
        _support_guard_features(
            last_close=_safe_float(features.get("last_close"), 0.0),
            day_low=_safe_float(features.get("day_low"), 0.0),
            daily_context=daily_context,
        )
    )
    features["tail_blowoff_reversal"] = _is_tail_blowoff_reversal(features)
    return features


_SIGNAL_TYPE_STYLE: dict[str, str] = {
    "sos": "trend",
    "jac": "trend",
    "spring": "pullback",
    "lps": "pullback",
    "evr": "hybrid",
}


def _normalize_signal_score(signal_score: float, signal_type: str) -> float:
    """按信号类型归一化 score 到 0-10 统一量纲。"""
    st = signal_type.strip().lower()
    raw = max(signal_score, 0.0)
    if st == "lps":
        # LPS score 是缩量比，越小越好（0.2=极干, 0.65=阈值边界）
        normalized = max(0.0, (0.65 - raw) / 0.65) * 10.0
    elif st in ("sos", "jac"):
        # SOS score 是放量倍数（2.5-8+），线性映射到 0-10
        normalized = min((raw - 2.0) / 4.0, 1.0) * 10.0
    elif st == "evr":
        # EVR score 是放量倍数（1.3-5+），线性映射
        normalized = min((raw - 1.0) / 3.0, 1.0) * 10.0
    elif st == "spring":
        # Spring score 是回升幅度%（0-10+），天然接近 0-10
        normalized = raw
    else:
        normalized = raw
    return min(max(normalized, 0.0), 10.0)


def _tail_style_bias(signal_type: str, style: str) -> tuple[str, float, float]:
    st_lower = signal_type.strip().lower()
    style_norm = str(style or "").strip().lower()
    if not style_norm or style_norm == "auto":
        style_norm = _SIGNAL_TYPE_STYLE.get(st_lower, "hybrid")
    if style_norm == "trend":
        return st_lower, 1.2, 0.8
    if style_norm in {"pullback", "reclaim"}:
        return st_lower, 0.8, 1.2
    return st_lower, 1.0, 1.0


def _score_signal_context(signal_score: float, st_lower: str, status: str, reasons: list[str]) -> float:
    score = 35.0
    sig_boost = _normalize_signal_score(signal_score, st_lower) * 1.6
    if sig_boost > 0:
        score += sig_boost
        reasons.append(f"漏斗信号加分({st_lower or '?'}) +{sig_boost:.1f}")
    if str(status).lower() == "confirmed":
        score += 6.0
        reasons.append("确认信号加分 +6.0")
    return score


def _score_tail_position(features: dict[str, Any], trend_bias: float, reasons: list[str]) -> float:
    score = 0.0
    dist_vwap_pct = _safe_float(features.get("dist_vwap_pct"), 0.0)
    if dist_vwap_pct >= 0.8:
        score += 16.0 * trend_bias
        reasons.append("尾盘在VWAP上方且有距离")
    elif dist_vwap_pct >= 0.0:
        score += 8.0 * trend_bias
        reasons.append("尾盘站上VWAP")
    else:
        score -= 12.0
        reasons.append("尾盘跌回VWAP下方")

    close_pos = _safe_float(features.get("close_pos"), 0.0)
    if close_pos >= 0.82:
        score += 14.0 * trend_bias
        reasons.append("收在日内高位区")
    elif close_pos >= 0.66:
        score += 8.0
        reasons.append("收位中高")
    elif close_pos < 0.45:
        score -= 12.0
        reasons.append("收位偏低")
    return score


def _score_tail_momentum(
    features: dict[str, Any],
    *,
    trend_bias: float,
    pullback_bias: float,
    reasons: list[str],
) -> float:
    score = 0.0
    last30_ret_pct = _safe_float(features.get("last30_ret_pct"), 0.0)
    if last30_ret_pct >= 1.0:
        score += 12.0 * trend_bias
        reasons.append("尾盘30分钟明显走强")
    elif last30_ret_pct >= 0.3:
        score += 6.0
        reasons.append("尾盘30分钟温和走强")
    elif last30_ret_pct <= -0.8:
        score -= 12.0
        reasons.append("尾盘30分钟转弱")

    last15_ret_pct = _safe_float(features.get("last15_ret_pct"), 0.0)
    if last15_ret_pct <= -0.5:
        score -= 8.0
        reasons.append("最后15分钟回落偏大")
    elif last15_ret_pct >= 0.4:
        score += 4.0
        reasons.append("最后15分钟维持抬升")
    return score + _score_tail_volume_and_breakout(features, trend_bias, pullback_bias, reasons)


def _score_tail_volume_and_breakout(
    features: dict[str, Any],
    trend_bias: float,
    pullback_bias: float,
    reasons: list[str],
) -> float:
    score = 0.0
    tail30_share = _safe_float(features.get("tail30_volume_share"), 0.0)
    if 0.14 <= tail30_share <= 0.45:
        score += 8.0
        reasons.append("尾段量能结构健康")
    elif tail30_share < 0.08:
        score -= 6.0
        reasons.append("尾段量能偏弱")
    elif tail30_share > 0.6:
        score -= 4.0
        reasons.append("尾段放量过猛，波动风险上升")
    if bool(features.get("reclaim_vwap")):
        score += 10.0 * pullback_bias
        reasons.append("出现回踩后再站上VWAP")
    if bool(features.get("strong_hold_vwap")):
        score += 10.0 * trend_bias
        reasons.append("全天强势守VWAP")
    if bool(features.get("breakout_tail")):
        score += 7.0 * trend_bias
        reasons.append("尾盘刷新前高/关键位")
    if _safe_float(features.get("drop_from_high_pct"), 0.0) <= -2.2:
        score -= 10.0
        reasons.append("收盘距日高回撤过大")
    return score + _score_slope(features)


def _score_slope(features: dict[str, Any]) -> float:
    slope_10 = _safe_float(features.get("slope_10_pct"), 0.0)
    if slope_10 >= 0.7:
        return 4.0
    if slope_10 <= -0.5:
        return -4.0
    return 0.0


def _score_tail_indicators(features: dict[str, Any], reasons: list[str]) -> float:
    score = 0.0
    vpc = _safe_float(features.get("vol_price_corr"), 0.0)
    if vpc > 0.3:
        score += 8.0
        reasons.append("量价正相关（涨时放量跌时缩量）")
    elif vpc < -0.3:
        score -= 8.0
        reasons.append("量价背离（涨时缩量跌时放量）")
    score += _score_effort_and_money(features, reasons)
    score += _score_spring_quality(features, reasons)
    return score


def _score_effort_and_money(features: dict[str, Any], reasons: list[str]) -> float:
    score = 0.0
    evr = _safe_float(features.get("effort_vs_result"), 0.0)
    if evr > 30:
        score += 6.0
        reasons.append("放量承接（高Effort低波动=吸筹）")
    elif evr < -30:
        score -= 6.0
        reasons.append("缩量大波动（虚假波动风险）")
    sms = _safe_float(features.get("smart_money_score"), 0.0)
    if sms > 1.0:
        score += 5.0
        reasons.append("尾盘聪明钱流入（量价齐升）")
    elif sms < -1.0:
        score -= 5.0
        reasons.append("尾盘聪明钱撤退（放量下跌）")
    return score


def _score_spring_quality(features: dict[str, Any], reasons: list[str]) -> float:
    spring_q = features.get("spring_quality")
    if spring_q is None:
        return 0.0
    if spring_q >= 70:
        reasons.append(f"分钟线Spring验证通过（{spring_q:.0f}分，快速收回支撑）")
        return 10.0
    if spring_q >= 50:
        reasons.append(f"分钟线Spring部分确认（{spring_q:.0f}分）")
        return 5.0
    if spring_q <= 20:
        reasons.append(f"分钟线Spring失败（{spring_q:.0f}分，跌破未收回）")
        return -5.0
    return 0.0


def _decision_from_score(score: float, status: str, reasons: list[str]) -> tuple[float, str, list[str]]:
    score = max(0.0, min(100.0, score))
    if score >= 72:
        decision = DECISION_BUY
    elif score >= 52:
        decision = DECISION_WATCH
    else:
        decision = DECISION_SKIP
    if decision == DECISION_BUY and _confirmed_only_buy_enabled() and _normalize_status(status) != "confirmed":
        decision = DECISION_WATCH
        reasons.append("未二次确认，尾盘只观察不买入")
    return score, decision, reasons


def score_tail_features(
    features: dict[str, Any],
    *,
    signal_score: float = 0.0,
    signal_type: str = "",
    status: str = "pending",
    style: str = "hybrid",
) -> tuple[float, str, list[str]]:
    """
    规则评分：输出 (分数, BUY/WATCH/SKIP, 理由列表)。
    style 支持 trend / pullback / hybrid；传空则按 signal_type 自动选择。
    """
    bars = int(_safe_float(features.get("bars"), 0))
    if bars < 60:
        return 5.0, DECISION_SKIP, ["分时数据不足（<60根1m）"]

    hard_veto_reasons = _tail_hard_veto_reasons(features)
    if hard_veto_reasons:
        return 20.0, DECISION_SKIP, hard_veto_reasons

    reasons: list[str] = []
    st_lower, trend_bias, pullback_bias = _tail_style_bias(signal_type, style)
    score = _score_signal_context(signal_score, st_lower, status, reasons)
    score += _score_tail_position(features, trend_bias, reasons)
    score += _score_tail_momentum(features, trend_bias=trend_bias, pullback_bias=pullback_bias, reasons=reasons)
    score += _score_tail_indicators(features, reasons)
    return _decision_from_score(score, status, reasons)


def _build_daily_context(snap: dict[str, Any]) -> dict[str, Any] | None:
    support = _safe_float(snap.get("snap_support"), 0.0)
    if support <= 0:
        return None
    return {"support_level": support, "snap_ma20": _safe_float(snap.get("snap_ma20"), 0.0)}


def evaluate_rule_decision(
    candidate: TailBuyCandidate,
    df_1m: pd.DataFrame,
    *,
    style: str = "auto",
) -> TailBuyCandidate:
    daily_context = _build_daily_context(candidate.snap) if candidate.snap else None
    features = compute_tail_features(df_1m, daily_context)
    score, decision, reasons = score_tail_features(
        features,
        signal_score=candidate.signal_score,
        signal_type=candidate.signal_type,
        status=candidate.status,
        style=style,
    )
    candidate.features = features
    candidate.rule_score = score
    candidate.rule_decision = decision
    candidate.rule_reasons = reasons
    candidate.final_decision = decision
    candidate.priority_score = score
    candidate.summary_5m = build_5m_summary(df_1m, max_bars=12)
    return _apply_unconfirmed_buy_gate(candidate)


def build_5m_summary(df_1m: pd.DataFrame, *, max_bars: int = 12) -> str:
    df = _ensure_intraday_df(df_1m)
    if df.empty:
        return "NO_DATA"
    x = df.set_index("datetime")[["open", "high", "low", "close", "volume"]]
    resampled = x.resample("5min", label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    resampled = resampled.dropna(subset=["close"]).tail(max(1, int(max_bars)))
    rows: list[str] = []
    for idx, row in resampled.iterrows():
        hhmm = idx.strftime("%H:%M")
        rows.append(
            f"{hhmm} O{_safe_float(row['open']):.2f} "
            f"H{_safe_float(row['high']):.2f} "
            f"L{_safe_float(row['low']):.2f} "
            f"C{_safe_float(row['close']):.2f} "
            f"V{int(max(_safe_float(row['volume']), 0.0))}"
        )
    return "\n".join(rows)


def build_llm_prompt(
    candidate: TailBuyCandidate,
    *,
    style: str = "hybrid",
    depth_info: dict | None = None,
) -> tuple[str, str]:
    f = candidate.features or {}
    style_desc = {
        "trend": "偏趋势（尾盘点火）",
        "pullback": "偏回踩再起",
        "hybrid": "混合型（尾盘走强 + 回踩再起）",
    }.get(str(style).lower(), "混合型（尾盘走强 + 回踩再起）")
    system_prompt = (
        "你是A股尾盘买入策略二判助手。"
        "你只能在 BUY/WATCH/SKIP 中选择一个结论，且必须返回 JSON。"
        "若 day_low_breached_support=true 或 tail_blowoff_reversal=true，必须选择 SKIP。"
        "禁止输出投资建议免责声明，禁止输出 markdown。"
    )
    user_prompt = (
        f"策略风格: {style_desc}\n"
        f"股票: {candidate.code} {candidate.name}\n"
        f"信号: status={candidate.status}, type={candidate.signal_type}, signal_score={candidate.signal_score:.2f}\n"
        f"规则一判: {candidate.rule_decision}, rule_score={candidate.rule_score:.1f}\n"
        "规则特征:\n"
        f"- close_pos={_safe_float(f.get('close_pos')):.3f}\n"
        f"- dist_vwap_pct={_safe_float(f.get('dist_vwap_pct')):.3f}\n"
        f"- last30_ret_pct={_safe_float(f.get('last30_ret_pct')):.3f}\n"
        f"- last15_ret_pct={_safe_float(f.get('last15_ret_pct')):.3f}\n"
        f"- tail30_volume_share={_safe_float(f.get('tail30_volume_share')):.3f}\n"
        f"- support_level={_safe_float(f.get('support_level')):.3f}\n"
        f"- day_low_vs_support_pct={_safe_float(f.get('day_low_vs_support_pct')):.3f}\n"
        f"- day_low_breached_support={bool(f.get('day_low_breached_support'))}\n"
        f"- intraday_high_ret_pct={_safe_float(f.get('intraday_high_ret_pct')):.3f}\n"
        f"- tail_blowoff_reversal={bool(f.get('tail_blowoff_reversal'))}\n"
        f"- strong_hold_vwap={bool(f.get('strong_hold_vwap'))}, hold_vwap_ratio={_safe_float(f.get('hold_vwap_ratio')):.3f}\n"
        f"- reclaim_vwap={bool(f.get('reclaim_vwap'))}\n"
        f"- breakout_tail={bool(f.get('breakout_tail'))}\n"
        f"- drop_from_high_pct={_safe_float(f.get('drop_from_high_pct')):.3f}\n"
        "最近5m摘要:\n"
        f"{candidate.summary_5m or 'NO_DATA'}\n"
    )
    if depth_info:
        user_prompt += (
            f"\n[五档] 委比: {depth_info.get('weibi', 0):.1f}% | "
            f"买盘总量: {depth_info.get('bid_total', 0)}手 | "
            f"卖盘总量: {depth_info.get('ask_total', 0)}手\n"
        )
    user_prompt += '\n请输出严格 JSON：{"decision":"BUY|WATCH|SKIP","reason":"<=80字","risk":"<=40字","confidence":0.0}'
    return system_prompt, user_prompt


def parse_llm_decision(raw_text: str) -> dict[str, Any] | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(text)
    except Exception:
        logger.debug("Direct JSON parse failed, trying regex extraction", exc_info=True)
    if parsed is None:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None
    if not isinstance(parsed, dict):
        return None
    decision = str(parsed.get("decision", "") or "").strip().upper()
    if decision not in VALID_DECISIONS:
        return None
    reason = str(parsed.get("reason", "") or "").strip()
    risk = str(parsed.get("risk", "") or "").strip()
    confidence = parsed.get("confidence")
    try:
        conf_value = float(confidence)
    except Exception:
        conf_value = None
    if conf_value is not None:
        conf_value = max(0.0, min(1.0, conf_value))
    return {
        "decision": decision,
        "reason": reason,
        "risk": risk,
        "confidence": conf_value,
    }


def select_llm_overlay_candidates(
    candidates: list[TailBuyCandidate],
    *,
    max_llm_symbols: int,
    min_rule_score: float = 60.0,
    allowed_rule_decisions: tuple[str, ...] = (DECISION_BUY, DECISION_WATCH),
) -> list[TailBuyCandidate]:
    """
    在 Python 规则层先收紧 LLM 二判候选：
    - 仅保留无 fetch_error 的标的
    - 仅保留规则结论在 allowed_rule_decisions 内的标的
    - 仅保留 rule_score >= min_rule_score 的标的
    - 最后按 rule_score 倒序截断到 max_llm_symbols
    """
    limit = max(int(max_llm_symbols), 0)
    if limit <= 0 or not candidates:
        return []

    allowed = {str(x or "").strip().upper() for x in (allowed_rule_decisions or ()) if str(x or "").strip()}
    if not allowed:
        return []

    floor = max(_safe_float(min_rule_score, 0.0), 0.0)
    selected = [
        item
        for item in candidates
        if not item.fetch_error
        and str(item.rule_decision or "").strip().upper() in allowed
        and _safe_float(item.rule_score, 0.0) >= floor
    ]
    selected.sort(key=lambda x: (-x.rule_score, x.code))
    return selected[:limit]


def merge_rule_and_llm(
    candidates: list[TailBuyCandidate],
    llm_result_by_code: dict[str, dict[str, Any]] | None = None,
) -> list[TailBuyCandidate]:
    llm_result_by_code = llm_result_by_code or {}
    decision_bonus = {
        DECISION_BUY: 12.0,
        DECISION_WATCH: 3.0,
        DECISION_SKIP: -20.0,
    }
    out: list[TailBuyCandidate] = []
    for item in candidates or []:
        code = normalize_cn_code(item.code)
        hard_veto_reasons = _tail_hard_veto_reasons(item.features)
        if hard_veto_reasons:
            item.llm_decision = None
            item.final_decision = DECISION_SKIP
            item.priority_score = min(item.rule_score, 20.0) - 20.0
            item.rule_reasons = hard_veto_reasons
            out.append(item)
            continue
        llm = llm_result_by_code.get(code) or {}
        llm_decision = str(llm.get("decision", "") or "").strip().upper()
        if llm_decision in VALID_DECISIONS:
            item.llm_decision = llm_decision
            item.llm_model_used = str(llm.get("model_used", "") or "").strip()
            reason = str(llm.get("reason", "") or "").strip()
            risk = str(llm.get("risk", "") or "").strip()
            if risk:
                reason = f"{reason}；风险:{risk}" if reason else f"风险:{risk}"
            item.llm_reason = reason
            conf = llm.get("confidence")
            conf_val: float | None
            try:
                conf_val = float(conf) if conf is not None else None
                if conf_val is not None and math.isnan(conf_val):
                    conf_val = None
            except Exception:
                conf_val = None
            item.llm_confidence = conf_val
            item.final_decision = llm_decision
            item.priority_score = item.rule_score + decision_bonus.get(llm_decision, 0.0)
        else:
            item.final_decision = item.rule_decision
            item.priority_score = item.rule_score + decision_bonus.get(item.rule_decision, 0.0)
        item = _apply_unconfirmed_buy_gate(item)
        out.append(item)
    out.sort(key=lambda x: (-x.priority_score, -x.rule_score, x.code))
    return out


def summarize_decision_counts(candidates: list[TailBuyCandidate]) -> dict[str, int]:
    out = {DECISION_BUY: 0, DECISION_WATCH: 0, DECISION_SKIP: 0}
    for item in candidates or []:
        decision = str(item.final_decision or "").strip().upper()
        if decision in out:
            out[decision] += 1
    return out


def _clean_extra_sections(extra_sections: list[str] | None) -> list[str]:
    return [text for section in extra_sections or [] if (text := str(section or "").strip())]


def build_tail_buy_markdown(
    *,
    now_text: str,
    target_signal_date: str,
    market_reminder: str,
    candidates: list[TailBuyCandidate],
    llm_total: int,
    llm_success: int,
    elapsed_seconds: float,
    extra_sections: list[str] | None = None,
    extra_sections_first: bool = False,
    max_error_items_per_block: int = 5,
    candidate_source: str | None = None,
    buy_only: bool = False,
    data_fetched_at: str = "",
) -> str:
    counts = summarize_decision_counts(candidates)
    source_text = str(candidate_source or "").strip() or (
        f"signal_pending（signal_date={target_signal_date}, status in pending/confirmed）"
    )
    lines: list[str] = [
        f"⏰ Tail Buy {now_text}",
        "",
        f"- 候选来源: {source_text}",
        f"- 扫描数量: {len(candidates)}",
        f"- 分层结果: BUY={counts[DECISION_BUY]}"
        + ("" if buy_only else f" / WATCH={counts[DECISION_WATCH]} / SKIP={counts[DECISION_SKIP]}"),
        f"- AI 二判: {llm_success}/{llm_total}",
        f"- 分时数据获取: {data_fetched_at}" if data_fetched_at else "- 分时数据获取: -",
        f"- 总耗时: {elapsed_seconds:.1f}s",
        "",
        f"⚠️ 风险提醒: {market_reminder}",
        "",
    ]

    def _append_block(title: str, decision: str) -> None:
        block = [x for x in candidates if x.final_decision == decision]
        lines.append(f"## {title}")
        if not block:
            lines.append("- 无")
            lines.append("")
            return
        max_error_items = max(int(max_error_items_per_block), 1)
        error_items = [x for x in block if str(x.fetch_error or "").strip()]
        normal_items = [x for x in block if not str(x.fetch_error or "").strip()]
        show_items = normal_items + error_items[:max_error_items]
        for item in show_items:
            reasons = "；".join(item.rule_reasons[:2]) if item.rule_reasons else "规则信号一般"
            llm_tag = ""
            if item.llm_decision:
                llm_tag = f" | AI:{item.llm_decision}"
            llm_reason = f" | {item.llm_reason}" if item.llm_reason else ""
            add_tag = "[加仓] " if item.signal_type == "holding" else ""
            lines.append(
                f"- {add_tag}{item.code} {item.name} | priority={item.priority_score:.1f} | "
                f"rule={item.rule_decision}({item.rule_score:.1f}){llm_tag}"
                f" | {reasons}{llm_reason}"
            )
        omitted_errors = max(len(error_items) - max_error_items, 0)
        if omitted_errors > 0:
            lines.append(f"- ... 其余 {omitted_errors} 只报错标的已省略（详见日志 artifacts）")
        lines.append("")

    cleaned_sections = _clean_extra_sections(extra_sections)

    if extra_sections_first:
        for text in cleaned_sections:
            lines.append(text)
            lines.append("")

    _append_block("BUY（优先关注）", DECISION_BUY)
    if not buy_only:
        _append_block("WATCH（观察）", DECISION_WATCH)
        _append_block("SKIP（暂不买入）", DECISION_SKIP)

    if not extra_sections_first:
        for text in cleaned_sections:
            lines.append(text)
            lines.append("")
    lines.append("说明：本任务仅输出尾盘扫描建议，不生成订单，不写入交易表。")
    return "\n".join(lines).strip() + "\n"
