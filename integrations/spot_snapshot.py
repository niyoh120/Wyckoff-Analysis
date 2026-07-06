"""A-share realtime spot snapshot helpers."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

import pandas as pd

from utils.env import env_flag

logger = logging.getLogger(__name__)

SPOT_SNAPSHOT_TTL_SECONDS = int(os.getenv("SPOT_SNAPSHOT_TTL_SECONDS", "20"))
SPOT_SNAPSHOT_TIMEOUT_SECONDS = float(os.getenv("SPOT_SNAPSHOT_TIMEOUT_SECONDS", "8.0"))
SPOT_TURNOVER_MAX_REL_ERR = float(os.getenv("SPOT_TURNOVER_MAX_REL_ERR", "0.35"))
SPOT_SNAPSHOT_TS = 0.0
SPOT_SNAPSHOT_MAP: dict[str, dict[str, float | None]] = {}
SPOT_SNAPSHOT_LOCK = threading.RLock()


def load_spot_snapshot_map(force_refresh: bool = False) -> dict[str, dict[str, float | None]]:
    global SPOT_SNAPSHOT_TS, SPOT_SNAPSHOT_MAP
    if _spot_cache_valid(force_refresh, time.time()):
        return SPOT_SNAPSHOT_MAP
    with SPOT_SNAPSHOT_LOCK:
        now_ts = time.time()
        if _spot_cache_valid(force_refresh, now_ts):
            return SPOT_SNAPSHOT_MAP
        try:
            SPOT_SNAPSHOT_MAP = parse_spot_dataframe(fetch_spot_dataframe())
            SPOT_SNAPSHOT_TS = now_ts
            return SPOT_SNAPSHOT_MAP
        except FuturesTimeoutError:
            _debug_spot_fail(
                "spot_snapshot",
                TimeoutError(f"timeout>{SPOT_SNAPSHOT_TIMEOUT_SECONDS:.1f}s"),
            )
            return SPOT_SNAPSHOT_MAP
        except Exception as exc:
            _debug_spot_fail("spot_snapshot", exc)
            return SPOT_SNAPSHOT_MAP


def fetch_stock_spot_snapshot(
    symbol: str,
    *,
    force_refresh: bool = False,
) -> dict[str, float | None] | None:
    normalized = normalize_spot_symbol(symbol)
    if not normalized:
        return None
    return load_spot_snapshot_map(force_refresh=force_refresh).get(normalized)


def fetch_spot_dataframe():
    import akshare as ak

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(ak.stock_zh_a_spot_em)
        df = future.result(timeout=max(SPOT_SNAPSHOT_TIMEOUT_SECONDS, 1.0))
    if df is None or df.empty:
        raise RuntimeError("spot snapshot empty")
    return df


def parse_spot_dataframe(df) -> dict[str, dict[str, float | None]]:
    code_col = _spot_code_column(df)
    spot_map: dict[str, dict[str, float | None]] = {}
    for _, row in df.iterrows():
        symbol = normalize_spot_symbol(row.get(code_col))
        if symbol:
            _append_spot_row(spot_map, symbol, row)
    if not spot_map:
        raise RuntimeError("spot snapshot parsed empty")
    return spot_map


def normalize_spot_symbol(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    match = re.search(r"(\d{6})", text)
    if match:
        return match.group(1)
    return text.zfill(6) if text.isdigit() else ""


def normalize_spot_turnover(
    close_v: float | None,
    volume_v: float | None,
    amount_v: float | None,
) -> tuple[float | None, float | None, bool]:
    if close_v is None or volume_v is None or amount_v is None:
        return (None, None, False)
    close = float(close_v)
    vol_raw = float(volume_v)
    amt_raw = float(amount_v)
    if close <= 0 or vol_raw <= 0 or amt_raw <= 0:
        return (None, None, False)
    best = _best_spot_turnover_units(close, vol_raw, amt_raw)
    if best is None:
        return (None, None, False)
    rel_err, vol_shares, amt_yuan = best
    if rel_err <= max(SPOT_TURNOVER_MAX_REL_ERR, 0.0):
        return (float(vol_shares), float(amt_yuan), True)
    return (None, None, False)


def _append_spot_row(spot_map: dict[str, dict[str, float | None]], symbol: str, row: pd.Series) -> None:
    close_v = _to_float_or_none(_pick_first(row, ("最新价", "最新", "现价", "收盘")))
    if close_v is None or close_v <= 0:
        return
    volume_v, amount_v, turnover_unit_ok = normalize_spot_turnover(
        close_v=close_v,
        volume_v=_to_float_or_none(_pick_first(row, ("成交量", "总手", "总量"))),
        amount_v=_to_float_or_none(_pick_first(row, ("成交额", "金额"))),
    )
    spot_map[symbol] = {
        "open": _to_float_or_none(_pick_first(row, ("今开", "开盘"))),
        "high": _to_float_or_none(_pick_first(row, ("最高",))),
        "low": _to_float_or_none(_pick_first(row, ("最低",))),
        "close": close_v,
        "volume": volume_v,
        "amount": amount_v,
        "pct_chg": _to_float_or_none(_pick_first(row, ("涨跌幅", "涨跌幅%"))),
        "turnover_unit_ok": 1.0 if turnover_unit_ok else 0.0,
    }


def _best_spot_turnover_units(close: float, volume_raw: float, amount_raw: float) -> tuple[float, float, float] | None:
    best: tuple[float, float, float] | None = None
    for volume_factor in (1.0, 100.0):
        vol_shares = volume_raw * volume_factor
        if vol_shares <= 0:
            continue
        for amount_factor in (1.0, 1000.0, 10000.0):
            amt_yuan = amount_raw * amount_factor
            if amt_yuan <= 0:
                continue
            rel_err = abs((amt_yuan / vol_shares) - close) / max(close, 1e-9)
            if best is None or rel_err < best[0]:
                best = (rel_err, vol_shares, amt_yuan)
    return best


def _spot_code_column(df) -> str:
    if "代码" in df.columns:
        return "代码"
    fallback_cols = [column for column in df.columns if "代码" in str(column)]
    if fallback_cols:
        return str(fallback_cols[0])
    raise RuntimeError("spot snapshot code column missing")


def _spot_cache_valid(force_refresh: bool, now_ts: float) -> bool:
    return (
        not force_refresh
        and bool(SPOT_SNAPSHOT_MAP)
        and (now_ts - SPOT_SNAPSHOT_TS) < max(SPOT_SNAPSHOT_TTL_SECONDS, 1)
    )


def _to_float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except Exception:
        return _float_from_text(value)


def _float_from_text(value: Any) -> float | None:
    try:
        text = str(value).strip().replace(",", "")
        if text.endswith("%"):
            text = text[:-1]
        return float(text)
    except Exception:
        return None


def _pick_first(row: pd.Series, candidates: tuple[str, ...]) -> Any:
    for key in candidates:
        if key in row.index:
            value = row.get(key)
            if value is not None and not pd.isna(value):
                return value
    return None


def _debug_spot_fail(source: str, err: Exception) -> None:
    if env_flag("DATA_SOURCE_DEBUG"):
        logger.debug("%s failed: %s: %s", source, type(err).__name__, err)
