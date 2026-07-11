"""Pure market breadth calculations."""

from __future__ import annotations

import pandas as pd


def calc_market_breadth(df_map: dict[str, pd.DataFrame], ma_window: int = 20) -> dict:
    valid_now = 0
    valid_prev = 0
    above_now = 0
    above_prev = 0
    daily_changes: list[float] = []
    window = max(int(ma_window), 2)
    for df in df_map.values():
        if df is None or df.empty:
            continue
        frame = _sorted_frame(df)
        close = pd.to_numeric(frame.get("close"), errors="coerce").dropna().tail(window + 1)
        if len(close) < window + 1:
            continue
        valid_now += 1
        valid_prev += 1
        above_now += int(float(close.iloc[-1]) >= float(close.iloc[1:].mean()))
        above_prev += int(float(close.iloc[-2]) >= float(close.iloc[:-1].mean()))
        if float(close.iloc[-2]) != 0:
            daily_changes.append((float(close.iloc[-1]) / float(close.iloc[-2]) - 1.0) * 100.0)
    ratio_now = above_now / valid_now * 100.0 if valid_now else None
    ratio_prev = above_prev / valid_prev * 100.0 if valid_prev else None
    delta = ratio_now - ratio_prev if ratio_now is not None and ratio_prev is not None else None
    daily = pd.Series(daily_changes, dtype=float)
    daily_total = int(len(daily))
    daily_up = int((daily > 0).sum())
    return {
        "ratio_pct": ratio_now,
        "prev_ratio_pct": ratio_prev,
        "delta_pct": delta,
        "sample_size": valid_now,
        "daily_sample_size": daily_total,
        "daily_up_count": daily_up,
        "daily_down_count": int((daily < 0).sum()),
        "daily_flat_count": int((daily == 0).sum()),
        "daily_up_ratio_pct": daily_up / daily_total * 100.0 if daily_total else None,
        "daily_median_pct_chg": float(daily.median()) if daily_total else None,
        "daily_average_pct_chg": float(daily.mean()) if daily_total else None,
    }


def _sorted_frame(df: pd.DataFrame) -> pd.DataFrame:
    if "date" not in df.columns:
        return df
    try:
        return df if df["date"].is_monotonic_increasing else df.sort_values("date")
    except Exception:
        return df.sort_values("date")
