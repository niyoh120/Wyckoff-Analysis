"""Daily-bar demand/supply signal for suspected institutional entry."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core._price_math import clamp as _clamp
from core._price_math import dist_pct as _dist_pct
from core._price_math import sort_by_date_if_needed


@dataclass(frozen=True)
class MainForceSignal:
    score: float
    labels: tuple[str, ...]
    metrics: dict[str, float]


EMPTY_MAIN_FORCE_SIGNAL = MainForceSignal(score=0.0, labels=(), metrics={})


def analyze_main_force_signal(df: pd.DataFrame | None) -> MainForceSignal:
    if df is None or df.empty or "close" not in df.columns:
        return EMPTY_MAIN_FORCE_SIGNAL
    ordered = sort_by_date_if_needed(df)
    close = _num(ordered, "close")
    if len(close) < 40:
        return EMPTY_MAIN_FORCE_SIGNAL
    high = _num(ordered, "high").reindex(close.index).fillna(close)
    low = _num(ordered, "low").reindex(close.index).fillna(close)
    amount = _amount_proxy(ordered, close)
    metrics = _signal_metrics(close, high, low, amount)
    score = _main_force_score(metrics)
    labels = tuple(_main_force_labels(metrics, score))
    return MainForceSignal(score=round(score, 4), labels=labels, metrics=_rounded_metrics(metrics, score))


def _signal_metrics(close: pd.Series, high: pd.Series, low: pd.Series, amount: pd.Series) -> dict[str, float]:
    ret = close.pct_change()
    amount20 = float(amount.tail(20).mean())
    up_amount = _masked_mean(amount.tail(10), ret.tail(10) > 0)
    down_amount = _masked_mean(amount.tail(10), ret.tail(10) < 0)
    close_pos = _close_position(close, high, low)
    last = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma50 = float(close.tail(50).mean()) if len(close) >= 50 else ma20
    support20 = float(low.tail(20).min())
    prev_high20 = float(high.tail(21).iloc[:-1].max()) if len(high) >= 21 else float(high.tail(20).max())
    return {
        "amount_ratio_5_20": _ratio(float(amount.tail(5).mean()), amount20),
        "amount_ratio_last_20": _ratio(float(amount.iloc[-1]), amount20),
        "up_amount_ratio_10_20": _ratio(up_amount, amount20),
        "down_amount_ratio_10_20": _ratio(down_amount, amount20),
        "demand_supply_ratio": _ratio(up_amount, max(down_amount, amount20 * 0.25)),
        "positive_amount_days_10": _positive_amount_days(ret.tail(10), amount.tail(10), amount20),
        "close_pos_day": float(close_pos.iloc[-1]),
        "close_pos5": float(close_pos.tail(5).mean()),
        "close_pos10": float(close_pos.tail(10).mean()),
        "dist_ma20": _dist_pct(last, ma20),
        "dist_ma50": _dist_pct(last, ma50),
        "support_hold_score": _support_hold_score(last, float(low.iloc[-1]), ma20, ma50, support20),
        "breakout_confirmed": float(last >= prev_high20 * 0.995 and float(close_pos.iloc[-1]) >= 0.70),
    }


def _main_force_score(metrics: dict[str, float]) -> float:
    demand = 0.45 * _clamp((metrics["up_amount_ratio_10_20"] - 0.75) / 1.25)
    demand += 0.35 * _clamp((metrics["demand_supply_ratio"] - 0.85) / 1.15)
    demand += 0.20 * _clamp(metrics["positive_amount_days_10"] / 0.55)
    supply = 0.55 * _clamp((1.30 - metrics["down_amount_ratio_10_20"]) / 1.05)
    supply += 0.25 * _clamp(metrics["close_pos5"])
    supply += 0.20 * _clamp(metrics["support_hold_score"])
    price = 0.35 * _clamp(metrics["close_pos_day"])
    price += 0.30 * _clamp(metrics["support_hold_score"])
    price += 0.20 * _clamp((8.0 - abs(metrics["dist_ma20"])) / 8.0)
    price += 0.15 * metrics["breakout_confirmed"]
    return _clamp(0.38 * demand + 0.34 * supply + 0.28 * price)


def _main_force_labels(metrics: dict[str, float], score: float) -> list[str]:
    labels: list[str] = []
    if score >= 0.68:
        labels.append("疑似资金进场")
    if metrics["demand_supply_ratio"] >= 1.20 and metrics["up_amount_ratio_10_20"] >= 0.95:
        labels.append("主动需求增强")
    if metrics["down_amount_ratio_10_20"] <= 0.90 and metrics["close_pos5"] >= 0.55:
        labels.append("缩量承接")
    if metrics["breakout_confirmed"] >= 1:
        labels.append("突破确认")
    if metrics["amount_ratio_last_20"] >= 1.8 and metrics["close_pos_day"] <= 0.45:
        labels.append("放量冲高回落风险")
    if metrics["down_amount_ratio_10_20"] >= 1.25 and metrics["close_pos5"] <= 0.48:
        labels.append("供给未消化")
    return labels


def _rounded_metrics(metrics: dict[str, float], score: float) -> dict[str, float]:
    out = {key: round(float(value), 4) for key, value in metrics.items()}
    out["main_force_score"] = round(float(score), 4)
    return out


def _amount_proxy(df: pd.DataFrame, close: pd.Series) -> pd.Series:
    amount = _num(df, "amount").reindex(close.index)
    if amount.notna().sum() >= 20 and float(amount.fillna(0).tail(20).sum()) > 0:
        return amount.fillna(0.0)
    volume = _num(df, "volume").reindex(close.index).fillna(0.0)
    return volume * close


def _close_position(close: pd.Series, high: pd.Series, low: pd.Series) -> pd.Series:
    span = (high - low).where((high - low) != 0)
    return ((close - low) / span).clip(lower=0.0, upper=1.0).fillna(0.5)


def _positive_amount_days(ret: pd.Series, amount: pd.Series, amount20: float) -> float:
    if amount20 <= 0 or ret.empty:
        return 0.0
    return float(((ret > 0) & (amount >= amount20 * 0.90)).mean())


def _support_hold_score(last: float, last_low: float, ma20: float, ma50: float, support20: float) -> float:
    checks = [
        last >= ma20 * 0.98 if ma20 > 0 else False,
        last >= ma50 * 0.97 if ma50 > 0 else False,
        last_low >= support20 * 0.985 if support20 > 0 else False,
    ]
    return sum(1 for ok in checks if ok) / len(checks)


def _masked_mean(values: pd.Series, mask: pd.Series) -> float:
    selected = values[mask.reindex(values.index).fillna(False)]
    return float(selected.mean()) if not selected.empty else 0.0


def _ratio(value: float, base: float) -> float:
    return 0.0 if base <= 0 else float(value) / float(base)


def _num(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce")
