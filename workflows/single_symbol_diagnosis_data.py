"""Market-data loading for single-symbol funnel diagnosis."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from core.wyckoff_engine import normalize_hist_from_fetch
from integrations.data_source import fetch_stock_hist
from integrations.fetch_a_share_csv import get_stocks_by_board
from integrations.index_data_source import fetch_index_hist
from integrations.market_metadata import fetch_market_cap_map, fetch_sector_map
from integrations.tickflow_client import TickFlowClient
from tools.market_universe_meta import load_symbol_name_map


@dataclass(frozen=True)
class SingleSymbolContextData:
    name_map: dict[str, str]
    market_cap_map: dict[str, float]
    sector_map: dict[str, str]
    bench_df: pd.DataFrame | None


def fetch_symbol_history(spec: Any, start: date, end: date, trading_days: int) -> pd.DataFrame:
    fetch_start = start - timedelta(days=max(trading_days * 3, 760))
    if spec.market == "cn":
        raw = fetch_stock_hist(spec.symbol, fetch_start, end, adjust="qfq")
    else:
        raw = _fetch_tickflow_daily(spec.symbol, fetch_start, end, trading_days)
    return prepare_symbol_history(raw, start, end, trading_days)


def load_symbol_context(
    spec: Any,
    hist: pd.DataFrame,
    start: date,
    end: date,
    log: Callable[[str], None] | None = None,
) -> SingleSymbolContextData:
    name_map = _name_map(spec)
    if spec.market != "cn":
        return SingleSymbolContextData(name_map, {}, {}, None)
    logger = log or (lambda _msg: None)
    return SingleSymbolContextData(
        name_map,
        _safe_fetch_market_cap_map(logger),
        _safe_fetch_sector_map(logger),
        _safe_fetch_benchmark(start, end, hist, logger),
    )


def load_rps_universe_histories(
    spec: Any,
    start: date,
    end: date,
    rps_window: int = 150,
    log: Callable[[str], None] | None = None,
) -> dict[str, pd.DataFrame]:
    if spec.market != "cn":
        return {}
    logger = log or (lambda _msg: None)
    symbols = _rps_symbols(spec)
    if not symbols:
        return {}
    logger(f"[diagnosis] RPS 全市场加载: universe={len(symbols)} symbols")
    client = TickFlowClient(api_key=os.getenv("TICKFLOW_API_KEY", ""))
    out = _fetch_rps_batches(client, symbols, end, rps_window, logger)
    logger(f"[diagnosis] RPS 历史加载完成: fetched={len(out)}/{len(symbols)}")
    return out


def prepare_symbol_history(raw: pd.DataFrame, start: date, end: date, trading_days: int) -> pd.DataFrame:
    df = normalize_hist_from_fetch(raw)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).copy()
    df["date_obj"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date_obj"]).sort_values("date_obj").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date_obj"]).dt.strftime("%Y-%m-%d")
    first_idx = _first_index_on_or_after(df, start)
    if first_idx is None:
        return pd.DataFrame()
    trim_from = max(first_idx - trading_days, 0)
    return df[(df.index >= trim_from) & (df["date_obj"] <= end)].reset_index(drop=True)


def _fetch_tickflow_daily(symbol: str, start: date, end: date, trading_days: int) -> pd.DataFrame:
    client = TickFlowClient(api_key=os.getenv("TICKFLOW_API_KEY", ""))
    start_ms = _date_to_utc_ms(start)
    end_ms = _date_to_utc_ms(end + timedelta(days=1))
    count = max((end - start).days + 10, trading_days * 3, 1200)
    return client.get_klines(
        symbol,
        period="1d",
        count=count,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        adjust="forward",
    )


def _name_map(spec: Any) -> dict[str, str]:
    if spec.market in {"hk", "us"}:
        names = load_symbol_name_map((spec.market,))
        return {spec.symbol: names.get(spec.symbol, spec.symbol)}
    return {spec.symbol: spec.symbol}


def _safe_fetch_market_cap_map(log: Callable[[str], None]) -> dict[str, float]:
    try:
        return fetch_market_cap_map()
    except Exception as exc:
        log(f"[diagnosis] 市值映射获取失败，跳过市值精确诊断: {exc}")
        return {}


def _safe_fetch_sector_map(log: Callable[[str], None]) -> dict[str, str]:
    try:
        return fetch_sector_map()
    except Exception as exc:
        log(f"[diagnosis] 行业映射获取失败，跳过行业精确诊断: {exc}")
        return {}


def _safe_fetch_benchmark(
    start: date, end: date, hist: pd.DataFrame, log: Callable[[str], None]
) -> pd.DataFrame | None:
    try:
        bench_start = min(hist["date_obj"]) if not hist.empty else start
        return fetch_index_hist("000001", bench_start, end)
    except Exception as exc:
        log(f"[diagnosis] 大盘基准获取失败，Layer2 相对强弱会降级: {exc}")
        return None


def _rps_symbols(spec: Any) -> list[str]:
    items = get_stocks_by_board("all")
    symbols = [str(item["code"]).strip() for item in items if item.get("code")]
    return [symbol for symbol in symbols if symbol and symbol != spec.symbol]


def _fetch_rps_batches(
    client: TickFlowClient,
    symbols: list[str],
    end: date,
    rps_window: int,
    log: Callable[[str], None],
) -> dict[str, pd.DataFrame]:
    count = rps_window + 30
    end_ms = _date_to_utc_ms(end + timedelta(days=1))
    out: dict[str, pd.DataFrame] = {}
    chunks = [symbols[index : index + 200] for index in range(0, len(symbols), 200)]
    for idx, chunk in enumerate(chunks, 1):
        log(f"[diagnosis] RPS K线批次 {idx}/{len(chunks)}")
        batch = client.get_klines_batch(chunk, period="1d", count=count, end_time_ms=end_ms, adjust="forward")
        out.update(_normalized_rps_batch(batch, rps_window))
    return out


def _normalized_rps_batch(batch: dict[str, pd.DataFrame], rps_window: int) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol, df in batch.items():
        norm = normalize_hist_from_fetch(df)
        if norm is not None and len(norm) >= rps_window:
            out[symbol] = norm
    return out


def _first_index_on_or_after(df: pd.DataFrame, day: date) -> int | None:
    hits = df.index[df["date_obj"] >= day]
    return int(hits[0]) if len(hits) else None


def _date_to_utc_ms(day: date) -> int:
    dt = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return int(dt.timestamp() * 1000)
