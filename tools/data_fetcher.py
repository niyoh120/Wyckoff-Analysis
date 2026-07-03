"""OHLCV fetch facade.

This module keeps the public batch-fetch API stable while concrete fetching
strategies live in dedicated modules.
"""

from __future__ import annotations

import logging

import pandas as pd

import tools.ohlcv_fallback_fetcher as ohlcv_fallback_fetcher
import tools.tickflow_batch_fetcher as tickflow_batch_fetcher
from core.hist_dates import latest_trade_date_from_hist as latest_trade_date_from_hist

logger = logging.getLogger(__name__)


def fetch_all_ohlcv(
    symbols: list[str],
    window,
    *,
    enforce_target_trade_date: bool = False,
    batch_size: int = ohlcv_fallback_fetcher.BATCH_SIZE,
    max_workers: int = ohlcv_fallback_fetcher.MAX_WORKERS,
    batch_timeout: int = ohlcv_fallback_fetcher.BATCH_TIMEOUT,
    batch_sleep: float = ohlcv_fallback_fetcher.BATCH_SLEEP,
    executor_mode: str = ohlcv_fallback_fetcher.EXECUTOR_MODE,
    direct_source: bool = False,
    runtime_config: ohlcv_fallback_fetcher.FetchRuntimeConfig | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, int | float]]:
    """Fetch daily OHLCV using the fastest available strategy."""
    batch_result = tickflow_batch_fetcher.fetch_tickflow_daily_batch(
        symbols=symbols,
        window=window,
        enforce_target_trade_date=enforce_target_trade_date,
        batch_size=batch_size,
        batch_sleep=batch_sleep,
    )
    if batch_result is not None:
        return batch_result

    return ohlcv_fallback_fetcher.fetch_ohlcv_fallback(
        symbols=symbols,
        window=window,
        enforce_target_trade_date=enforce_target_trade_date,
        batch_size=batch_size,
        max_workers=max_workers,
        batch_timeout=batch_timeout,
        batch_sleep=batch_sleep,
        executor_mode=executor_mode,
        direct_source=direct_source,
        runtime_config=runtime_config,
    )
