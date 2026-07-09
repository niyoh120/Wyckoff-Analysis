"""Phase 1: HK/US 回测数据快照抓取（TickFlow 数据源）。

港股基准候选列表带回退（TickFlow 不支持任何形式的恒生指数代码，改用
02800.HK/03033.HK 等 ETF 代理），美股基准固定为 SPY.US 单一候选；两者共用
同一套批量抓取/落盘流程，差异集中在 MarketSnapshotConfig。A股快照抓取走
完全不同的 akshare 数据源与元数据管线，见 workflows/backtest_snapshot_fetch.py。
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from core.wyckoff_engine import normalize_hist_from_fetch
from integrations.market_universe import load_hk_symbols, load_us_symbols
from integrations.tickflow_client import TickFlowClient

Market = Literal["hk", "us"]


@dataclass(frozen=True)
class MarketSnapshotConfig:
    market: Market
    batch_size: int
    batch_sleep: float
    benchmark_candidates: tuple[str, ...]
    load_symbols: Callable[[], tuple[list[str], dict[str, str]]]


def _hk_benchmark_candidates() -> tuple[str, ...]:
    # 实测 TickFlow 不支持任何形式的恒生指数代码（800000.HK/HSI.HK/^HSI/HSI 均返回空），
    # 改用 02800.HK（盈富基金 Tracker Fund，追踪恒生指数的港股 ETF）作为基准代理，
    # 历史数据完整覆盖 2020 年至今；03033.HK（南方恒生科技）作为科技股行情的备选代理。
    default = ("02800.HK", "03033.HK")
    return tuple(s.strip() for s in os.getenv("BACKTEST_HK_BENCHMARK", "").split(",") if s.strip()) or default


def _market_config(market: Market) -> MarketSnapshotConfig:
    prefix = market.upper()
    if market == "hk":
        return MarketSnapshotConfig(
            market="hk",
            batch_size=int(os.getenv(f"BACKTEST_{prefix}_KLINE_BATCH_SIZE", "100")),
            batch_sleep=float(os.getenv(f"BACKTEST_{prefix}_KLINE_BATCH_SLEEP", "2.0")),
            benchmark_candidates=_hk_benchmark_candidates(),
            load_symbols=load_hk_symbols,
        )
    return MarketSnapshotConfig(
        market="us",
        batch_size=int(os.getenv(f"BACKTEST_{prefix}_KLINE_BATCH_SIZE", "100")),
        batch_sleep=float(os.getenv(f"BACKTEST_{prefix}_KLINE_BATCH_SLEEP", "2.0")),
        benchmark_candidates=(os.getenv("BACKTEST_US_BENCHMARK", "SPY.US"),),
        load_symbols=load_us_symbols,
    )


def _fetch_klines_batched(
    client: TickFlowClient,
    symbols: list[str],
    count: int,
    start_ms: int,
    end_ms: int,
    config: MarketSnapshotConfig,
) -> dict[str, pd.DataFrame]:
    tag = f"[{config.market}-snapshot]"
    all_dfs: dict[str, pd.DataFrame] = {}
    chunks = [symbols[i : i + config.batch_size] for i in range(0, len(symbols), config.batch_size)]
    total = len(chunks)
    for idx, chunk in enumerate(chunks, 1):
        t0 = time.monotonic()
        try:
            batch = client.get_klines_batch(
                chunk,
                period="1d",
                count=count,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
                adjust="forward",
            )
            all_dfs.update(batch)
        except Exception as e:
            print(f"{tag} batch {idx}/{total} failed: {e}")
        elapsed = time.monotonic() - t0
        if idx < total:
            time.sleep(max(config.batch_sleep - elapsed, 0.1))
        if idx % 5 == 0 or idx == total:
            print(f"{tag} progress: {idx}/{total} batches, {len(all_dfs)} symbols fetched")
    return all_dfs


def _fetch_benchmark(
    client: TickFlowClient, count: int, start_ms: int, end_ms: int, config: MarketSnapshotConfig
) -> tuple[pd.DataFrame | None, str]:
    tag = f"[{config.market}-snapshot]"
    for symbol in config.benchmark_candidates:
        print(f"{tag} fetching benchmark: {symbol}")
        try:
            bench_map = client.get_klines_batch(
                [symbol], period="1d", count=count, start_time_ms=start_ms, end_time_ms=end_ms, adjust="forward"
            )
            raw = bench_map.get(symbol)
            norm = normalize_hist_from_fetch(raw) if raw is not None and not raw.empty else None
            if norm is not None and not norm.empty:
                return norm, symbol
        except Exception as e:
            print(f"{tag} benchmark fetch failed: {symbol}: {e}")
    return None, ""


def _save_snapshot(
    out_dir: Path,
    full_df: pd.DataFrame,
    bench_df: pd.DataFrame | None,
    bench_symbol: str,
    symbols: list[str],
    ok_count: int,
    name_map: dict[str, str],
    prefetch_start,
    end_dt,
    config: MarketSnapshotConfig,
) -> int:
    tag = f"[{config.market}-snapshot]"
    full_df.to_csv(out_dir / "hist_full.csv.gz", index=False, compression="gzip")
    print(f"{tag} hist_full.csv.gz: {len(full_df)} rows")

    if bench_df is not None and not bench_df.empty:
        bench_df.to_csv(out_dir / "benchmark_main.csv", index=False)
        print(f"{tag} benchmark_main.csv: {len(bench_df)} rows")
    else:
        print(f"{tag} WARNING: no benchmark data, backtest will fail without trade calendar")
        return 1

    (out_dir / "name_map.json").write_text(json.dumps(name_map, ensure_ascii=False), encoding="utf-8")
    (out_dir / "sector_map.json").write_text("{}", encoding="utf-8")
    (out_dir / "market_cap_map.json").write_text("{}", encoding="utf-8")
    meta = {
        "market": config.market,
        "symbols": len(symbols),
        "ok": ok_count,
        "fail": len(symbols) - ok_count,
        "start": prefetch_start.strftime("%Y%m%d"),
        "end": end_dt.strftime("%Y%m%d"),
        "benchmark": bench_symbol,
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"{tag} Done! {ok_count}/{len(symbols)} ({100 * ok_count / len(symbols):.1f}%)")
    return 0


def run_snapshot_fetch(args, *, market: Market) -> int:
    config = _market_config(market)
    tag = f"[{market}-snapshot]"
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        print(f"{tag} ERROR: TICKFLOW_API_KEY not set")
        return 1
    client = TickFlowClient(api_key=api_key)
    start_dt = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(args.end, "%Y-%m-%d").date()
    prefetch_start = start_dt - timedelta(days=int(args.trading_days * 2))
    start_ms = int(datetime.combine(prefetch_start, datetime.min.time()).timestamp() * 1000)
    end_ms = int(datetime.combine(end_dt, datetime.max.time()).timestamp() * 1000)
    count = (end_dt - prefetch_start).days + 50
    print(f"{tag} date range: {prefetch_start} -> {end_dt} (count={count})")

    symbols, name_map = config.load_symbols()
    if not symbols:
        print(f"{tag} ERROR: no {market.upper()} symbols found in data/market_universes/{market}.txt")
        return 1
    if args.max_symbols > 0 and len(symbols) > args.max_symbols:
        symbols = symbols[: args.max_symbols]
    print(f"{tag} symbol pool: {len(symbols)} (sample: {symbols[:5]})")

    df_map = _fetch_klines_batched(client, symbols, count, start_ms, end_ms, config)
    print(f"{tag} fetched: {len(df_map)}/{len(symbols)} symbols")
    if len(df_map) < len(symbols) * 0.1:
        print(f"{tag} ERROR: success rate {len(df_map)}/{len(symbols)} below 10%")
        return 1

    frames = [
        df.assign(symbol=sym)
        for sym, raw in df_map.items()
        if (df := normalize_hist_from_fetch(raw)) is not None and not df.empty
    ]
    if not frames:
        print(f"{tag} ERROR: no valid data after normalization")
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bench_df, bench_symbol = _fetch_benchmark(client, count, start_ms, end_ms, config)
    full_df = pd.concat(frames, ignore_index=True)
    return _save_snapshot(
        out_dir, full_df, bench_df, bench_symbol, symbols, len(df_map), name_map, prefetch_start, end_dt, config
    )
