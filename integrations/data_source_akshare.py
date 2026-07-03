"""AkShare stock-history provider."""

from __future__ import annotations

import os
import time
from http.client import RemoteDisconnected

import pandas as pd

from integrations.data_source_format import compact_error as _compact_error

_RETRY_TIMES = max(int(os.getenv("AKSHARE_RETRY_TIMES", "2")), 1)
_RETRY_SLEEP_SECONDS = float(os.getenv("AKSHARE_RETRY_SLEEP_SECONDS", "0.8"))


def fetch_stock_akshare(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    for attempt in range(1, _RETRY_TIMES + 1):
        try:
            return _fetch_stock_akshare_once(symbol, start, end, adjust)
        except ModuleNotFoundError:
            raise
        except Exception as exc:
            if attempt < _RETRY_TIMES and _is_retryable_akshare_error(exc):
                time.sleep(max(_RETRY_SLEEP_SECONDS, 0.0))
                continue
            raise
    raise RuntimeError("akshare retry exhausted")


def _fetch_stock_akshare_once(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    import akshare as ak

    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start,
        end_date=end,
        adjust=adjust if adjust else "",
    )
    if df is None or df.empty:
        raise RuntimeError("akshare empty")
    if "日期" in df.columns:
        df = df.copy()
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def _is_retryable_akshare_error(err: Exception) -> bool:
    text = _compact_error(err).lower()
    markers = [
        "remotedisconnected",
        "remote end closed connection",
        "connection aborted",
        "connection reset",
        "read timed out",
        "connecttimeout",
        "proxyerror",
    ]
    return any(m in text for m in markers) or isinstance(err, RemoteDisconnected)
