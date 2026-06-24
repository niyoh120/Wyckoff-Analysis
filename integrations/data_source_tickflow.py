"""TickFlow stock-history provider."""

from __future__ import annotations

import logging
import os
import threading

import pandas as pd

from integrations.data_source_format import (
    tickflow_adjust_mode,
    tickflow_daily_count,
    tickflow_daily_frame,
    tickflow_daily_window,
)
from integrations.tickflow_notice import TICKFLOW_LIMIT_HINT

logger = logging.getLogger(__name__)

_CLIENT = None
_CLIENT_READY = False
_DAILY_MAX_COUNT = max(int(os.getenv("TICKFLOW_DAILY_MAX_COUNT", "10000")), 64)
_LIMIT_NOTICE_EMITTED = False
_LIMIT_NOTICE_LOCK = threading.Lock()


def fetch_stock_tickflow(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    client = _get_tickflow_client()
    if client is None:
        raise RuntimeError("TICKFLOW_API_KEY 未配置")

    start_d, end_d, start_ms, end_ms = tickflow_daily_window(start, end)
    df = client.get_klines(
        symbol=symbol,
        period="1d",
        count=tickflow_daily_count(start_d, end_d, _DAILY_MAX_COUNT),
        intraday=False,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        adjust=tickflow_adjust_mode(adjust),
    )
    if df is None or df.empty:
        raise RuntimeError("tickflow empty")
    return tickflow_daily_frame(df, start_d, end_d)


def attach_tickflow_limit_notices(df: pd.DataFrame, notices: list[str] | None) -> pd.DataFrame:
    uniq: list[str] = []
    for item in notices or []:
        text = str(item or "").strip()
        if text and text not in uniq:
            uniq.append(text)
    if uniq:
        df.attrs["tickflow_limit_hint"] = uniq[0]
        df.attrs["tickflow_limit_hints"] = uniq
        _emit_tickflow_limit_notice_once()
    return df


def _get_tickflow_client():
    global _CLIENT, _CLIENT_READY
    if _CLIENT_READY:
        return _CLIENT
    _CLIENT_READY = True
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        _CLIENT = None
        return None
    try:
        from integrations.tickflow_client import TickFlowClient

        _CLIENT = TickFlowClient(api_key=api_key)
    except Exception:
        logger.debug("tickflow client init failed", exc_info=True)
        _CLIENT = None
    return _CLIENT


def _emit_tickflow_limit_notice_once() -> None:
    global _LIMIT_NOTICE_EMITTED
    with _LIMIT_NOTICE_LOCK:
        if _LIMIT_NOTICE_EMITTED:
            return
        _LIMIT_NOTICE_EMITTED = True
    logger.warning("TickFlow limit hint: %s", TICKFLOW_LIMIT_HINT)
