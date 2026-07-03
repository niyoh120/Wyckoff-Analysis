"""Shared price/volume math helpers used across candidate and mainline scoring modules.

These were duplicated verbatim in 5-7 files; centralized here so each formula has one
implementation to keep correct.
"""

from __future__ import annotations

import pandas as pd


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def numeric_column(df: pd.DataFrame, column: str, *, dropna: bool = True) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(df[column], errors="coerce")
    return series.dropna() if dropna else series


def ret_pct(close: pd.Series, lookback: int) -> float:
    if len(close) <= lookback:
        return 0.0
    start = float(close.iloc[-lookback - 1])
    return 0.0 if start <= 0 else (float(close.iloc[-1]) / start - 1.0) * 100.0


def dist_pct(value: float, base: float) -> float:
    return 0.0 if base <= 0 else (float(value) / float(base) - 1.0) * 100.0


def drawdown_pct(close: pd.Series, lookback: int) -> float:
    recent = close.tail(max(lookback, 1))
    if recent.empty:
        return 0.0
    high = float(recent.max())
    return 0.0 if high <= 0 else (float(recent.iloc[-1]) / high - 1.0) * -100.0


def upper_shadow_pct(df: pd.DataFrame, open_: pd.Series, high: pd.Series, close: pd.Series) -> float:
    if high.empty or close.empty:
        return 0.0
    base = float(close.iloc[-1])
    body_top = max(base, float(open_.iloc[-1]) if not open_.empty else base)
    return 0.0 if base <= 0 else max(float(high.iloc[-1]) - body_top, 0.0) / base * 100.0


def vol_ratio(volume: pd.Series) -> float:
    if len(volume) < 20:
        return 1.0
    base = float(volume.tail(20).mean())
    return 1.0 if base <= 0 else float(volume.tail(5).mean()) / base
