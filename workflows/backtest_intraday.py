"""Intraday entry-price adapters for backtest workflows."""

from __future__ import annotations

import os
from datetime import date

from core.backtest_execution import IntradayPriceFetcher, intraday_ms_window, price_at_or_before


def tickflow_entry_price_fetcher_from_env() -> IntradayPriceFetcher | None:
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        return None

    from integrations.tickflow_client import TickFlowClient

    client = TickFlowClient(api_key=api_key)

    def _fetch(code: str, day: date, entry_time: str, _cache: dict) -> tuple[float | None, str]:
        start_ms, end_ms = intraday_ms_window(day, entry_time)
        df = client.get_klines(
            code,
            period="1m",
            count=500,
            intraday=True,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
        )
        return price_at_or_before(df, day, entry_time), f"tickflow_1m_{entry_time}"

    return _fetch
