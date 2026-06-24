"""Pure historical price date helpers."""

from __future__ import annotations

from datetime import date

import pandas as pd


def latest_trade_date_from_hist(df: pd.DataFrame) -> date | None:
    if df is None or df.empty or "date" not in df.columns:
        return None
    series = pd.to_datetime(df["date"], errors="coerce").dropna()
    if series.empty:
        return None
    return series.iloc[-1].date()
