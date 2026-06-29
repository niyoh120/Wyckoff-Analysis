"""Candidate lane builders shared by live funnel and backtest replay."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.candidate_tracks import candidate_entry_key, candidate_entry_score, sanitized_candidate_entry


def build_l1_candidate_lane_entries(
    *,
    l1_symbols: list[str],
    df_map: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    top_sectors: list[str],
    l2_symbols: list[str],
    channel_map: dict[str, str],
    limit: int = 80,
) -> list[dict[str, Any]]:
    top_sector_set = {str(item).strip() for item in top_sectors if str(item).strip()}
    l2_set = {str(item).strip() for item in l2_symbols if str(item).strip()}
    rows = [
        _entry_for_code(
            code, df_map.get(code), sector_map.get(code, ""), code in l2_set, channel_map.get(code, ""), top_sector_set
        )
        for code in l1_symbols
    ]
    valid = [row for row in rows if row]
    valid.sort(key=lambda item: (-candidate_entry_score(item), str(item.get("code"))))
    return valid[: max(int(limit), 0)] if limit > 0 else valid


def merge_candidate_entries(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group or []:
            code = str(item.get("code", "")).strip()
            if not code:
                continue
            current = merged.get(code)
            if current is None or _entry_rank(item) < _entry_rank(current):
                merged[code] = sanitized_candidate_entry(item)
    return sorted(merged.values(), key=_entry_rank)


def _entry_for_code(
    code: str,
    df: pd.DataFrame | None,
    sector: str,
    l2_passed: bool,
    channel: str,
    top_sector_set: set[str],
) -> dict[str, Any] | None:
    metrics = _price_metrics(df)
    if not metrics:
        return None
    risks = _risk_flags(metrics)
    if _hard_blocked(risks):
        return None
    lane = _lane(metrics, sector in top_sector_set, l2_passed)
    if not lane:
        return None
    score = _lane_score(lane, metrics, sector in top_sector_set, l2_passed)
    if score < _lane_min_score(lane):
        return None
    return _candidate_entry(code, sector, lane, score, metrics, risks, channel)


def _candidate_entry(
    code: str,
    sector: str,
    lane: str,
    score: float,
    metrics: dict[str, float],
    risks: list[str],
    channel: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "track": "trend",
        "signal_key": lane,
        "entry_type": lane,
        "score": round(score, 2),
        "metrics": {key: round(float(value), 4) for key, value in metrics.items()},
        "opportunity": _opportunity_text(lane, sector),
        "timing": _timing_text(lane, metrics),
        "risk": " / ".join(risks) or "尾盘仍需二次确认",
        "state": "Lane",
        "lane": lane,
        "channel": channel,
        "reasons": _reasons(lane, metrics, sector),
    }


def _lane(metrics: dict[str, float], in_top_sector: bool, l2_passed: bool) -> str:
    if _trend_breakout(metrics):
        return "trend_breakout"
    if _trend_pullback(metrics):
        return "trend_lane_pullback"
    if in_top_sector and _sector_strength(metrics):
        return "sector_strength"
    if l2_passed and _trend_follow(metrics):
        return "wyckoff_structure"
    return ""


def _trend_breakout(metrics: dict[str, float]) -> bool:
    return (
        metrics["close_pos60"] >= 0.86
        and 8 <= metrics["ret20"] <= 38
        and metrics["ret60"] >= 18
        and -2 <= metrics["dist_ma20"] <= 14
        and 0.75 <= metrics["vol_ratio_5_20"] <= 2.4
    )


def _trend_pullback(metrics: dict[str, float]) -> bool:
    return (
        metrics["ret60"] >= 12
        and metrics["ret120"] >= 10
        and -3 <= metrics["dist_ma20"] <= 7
        and metrics["dist_ma50"] >= -3
        and metrics["vol_ratio_5_20"] <= 1.10
        and metrics["close_pos20"] >= 0.42
    )


def _sector_strength(metrics: dict[str, float]) -> bool:
    return (
        4 <= metrics["ret20"] <= 34
        and metrics["ret60"] >= 10
        and metrics["dist_ma20"] <= 12
        and metrics["close_pos20"] >= 0.55
    )


def _trend_follow(metrics: dict[str, float]) -> bool:
    return metrics["ret20"] >= 6 and metrics["ret60"] >= 8 and metrics["dist_ma20"] <= 12


def _lane_score(lane: str, metrics: dict[str, float], in_top_sector: bool, l2_passed: bool) -> float:
    base = {"trend_breakout": 72.0, "trend_lane_pullback": 70.0, "sector_strength": 66.0, "wyckoff_structure": 62.0}[
        lane
    ]
    strength = 12.0 * _clamp(metrics["ret60"] / 45.0) + 8.0 * _clamp(metrics["close_pos20"])
    distance = 6.0 * _clamp(1.0 - max(metrics["dist_ma20"] - 6.0, 0.0) / 12.0)
    context = (5.0 if in_top_sector else 0.0) + (3.0 if l2_passed else 0.0)
    return min(base + strength + distance + context, 100.0)


def _lane_min_score(lane: str) -> float:
    return {
        "trend_breakout": 78.0,
        "trend_lane_pullback": 76.0,
        "sector_strength": 74.0,
        "wyckoff_structure": 72.0,
    }[lane]


def _price_metrics(df: pd.DataFrame | None) -> dict[str, float]:
    if df is None or df.empty or "close" not in df.columns:
        return {}
    ordered = df.sort_values("date") if "date" in df.columns else df
    close = pd.to_numeric(ordered["close"], errors="coerce").dropna()
    if len(close) < 80:
        return {}
    high = _num(ordered, "high")
    low = _num(ordered, "low")
    open_ = _num(ordered, "open")
    volume = _num(ordered, "volume")
    last = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma50 = float(close.tail(50).mean())
    return {
        "ret5": _ret_pct(close, 5),
        "ret20": _ret_pct(close, 20),
        "ret60": _ret_pct(close, 60),
        "ret120": _ret_pct(close, 120),
        "dist_ma20": _dist_pct(last, ma20),
        "dist_ma50": _dist_pct(last, ma50),
        "close_pos20": _range_pos(last, low.tail(20), high.tail(20), close.tail(20)),
        "close_pos60": _range_pos(last, low.tail(60), high.tail(60), close.tail(60)),
        "close_pos_day": _day_close_pos(ordered, high, low),
        "upper_shadow_pct": _upper_shadow_pct(ordered, open_, high, close),
        "vol_ratio_5_20": _vol_ratio(volume),
    }


def _risk_flags(metrics: dict[str, float]) -> list[str]:
    risks: list[str] = []
    if metrics["dist_ma20"] > 18 or metrics["ret20"] > 45:
        risks.append("短线过热")
    if metrics["upper_shadow_pct"] > 5 and metrics["vol_ratio_5_20"] > 1.8 and metrics["close_pos_day"] < 0.45:
        risks.append("放量长上影")
    if metrics["dist_ma20"] < -6 or metrics["dist_ma50"] < -10:
        risks.append("跌破确认支撑")
    if metrics["ret20"] < -8 and metrics["vol_ratio_5_20"] < 0.9:
        risks.append("缩量阴跌")
    return risks


def _hard_blocked(risks: list[str]) -> bool:
    return bool(set(risks) & {"短线过热", "放量长上影", "跌破确认支撑", "缩量阴跌"})


def _opportunity_text(lane: str, sector: str) -> str:
    text = {
        "trend_breakout": "强趋势平台突破",
        "trend_lane_pullback": "主线趋势回踩确认",
        "sector_strength": "板块强势轮动候选",
        "wyckoff_structure": "Wyckoff结构延续候选",
    }.get(lane, lane)
    return f"{text}: {sector}" if sector else text


def _timing_text(lane: str, metrics: dict[str, float]) -> str:
    return (
        f"{lane} ret20={metrics['ret20']:.1f}% ret60={metrics['ret60']:.1f}% "
        f"MA20乖离={metrics['dist_ma20']:.1f}% 量={metrics['vol_ratio_5_20']:.2f}x"
    )


def _reasons(lane: str, metrics: dict[str, float], sector: str) -> list[str]:
    return [
        f"lane:{lane}",
        f"板块:{sector or '-'}",
        f"20日:{metrics['ret20']:.1f}%",
        f"60日:{metrics['ret60']:.1f}%",
        f"MA20乖离:{metrics['dist_ma20']:.1f}%",
    ]


def _entry_rank(item: dict[str, Any]) -> tuple[int, float, str]:
    priority = {
        "mainline": 0,
        "trend_lane_pullback": 1,
        "trend_breakout": 2,
        "sector_strength": 3,
        "wyckoff_structure": 4,
    }
    rank_key = _rank_key(item, priority)
    return (priority.get(rank_key, 20), -candidate_entry_score(item), str(item.get("code", "")))


def _rank_key(item: dict[str, Any], priority: dict[str, int]) -> str:
    return candidate_entry_key(item, priority.keys(), fields=("signal_key", "lane", "entry_type"))


def _num(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


def _ret_pct(close: pd.Series, lookback: int) -> float:
    if len(close) <= lookback:
        return 0.0
    start = float(close.iloc[-lookback - 1])
    return 0.0 if start <= 0 else (float(close.iloc[-1]) / start - 1.0) * 100.0


def _dist_pct(value: float, base: float) -> float:
    return 0.0 if base <= 0 else (value / base - 1.0) * 100.0


def _range_pos(value: float, lows: pd.Series, highs: pd.Series, fallback: pd.Series) -> float:
    low = float(lows.min()) if not lows.empty else float(fallback.min())
    high = float(highs.max()) if not highs.empty else float(fallback.max())
    return 0.5 if high <= low else _clamp((value - low) / (high - low))


def _day_close_pos(df: pd.DataFrame, high: pd.Series, low: pd.Series) -> float:
    if high.empty or low.empty:
        return 0.5
    return _range_pos(float(df["close"].iloc[-1]), low.tail(1), high.tail(1), df["close"].tail(1))


def _upper_shadow_pct(df: pd.DataFrame, open_: pd.Series, high: pd.Series, close: pd.Series) -> float:
    if high.empty or close.empty:
        return 0.0
    base = float(close.iloc[-1])
    body_top = max(base, float(open_.iloc[-1]) if not open_.empty else base)
    return 0.0 if base <= 0 else max(float(high.iloc[-1]) - body_top, 0.0) / base * 100.0


def _vol_ratio(volume: pd.Series) -> float:
    if len(volume) < 20:
        return 1.0
    base = float(volume.tail(20).mean())
    return 1.0 if base <= 0 else float(volume.tail(5).mean()) / base


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
