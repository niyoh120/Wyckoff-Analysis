"""Phase 1: 港股回测数据快照抓取（TickFlow 数据源）。"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from core.wyckoff_engine import normalize_hist_from_fetch
from integrations.market_universe import load_hk_symbols
from integrations.tickflow_client import TickFlowClient

BATCH_SIZE = int(os.getenv("BACKTEST_HK_KLINE_BATCH_SIZE", "100"))
BATCH_SLEEP = float(os.getenv("BACKTEST_HK_KLINE_BATCH_SLEEP", "2.0"))
# 实测 TickFlow 不支持任何形式的恒生指数代码（800000.HK/HSI.HK/^HSI/HSI 均返回空），
# 改用 02800.HK（盈富基金 Tracker Fund，追踪恒生指数的港股 ETF）作为基准代理，
# 历史数据完整覆盖 2020 年至今；03033.HK（南方恒生科技）作为科技股行情的备选代理。
_DEFAULT_BENCHMARK_CANDIDATES = ("02800.HK", "03033.HK")
BENCHMARK_SYMBOL_CANDIDATES = (
    tuple(s.strip() for s in os.getenv("BACKTEST_HK_BENCHMARK", "").split(",") if s.strip())
    or _DEFAULT_BENCHMARK_CANDIDATES
)


def _fetch_klines_batched(
    client: TickFlowClient,
    symbols: list[str],
    count: int,
    start_ms: int,
    end_ms: int,
) -> dict[str, pd.DataFrame]:
    all_dfs: dict[str, pd.DataFrame] = {}
    chunks = [symbols[i : i + BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]
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
            print(f"[hk-snapshot] batch {idx}/{total} failed: {e}")
        elapsed = time.monotonic() - t0
        if idx < total:
            sleep_time = max(BATCH_SLEEP - elapsed, 0.1)
            time.sleep(sleep_time)
        if idx % 5 == 0 or idx == total:
            print(f"[hk-snapshot] progress: {idx}/{total} batches, {len(all_dfs)} symbols fetched")
    return all_dfs


def _fetch_benchmark(client: TickFlowClient, count: int, start_ms: int, end_ms: int) -> tuple[pd.DataFrame | None, str]:
    for symbol in BENCHMARK_SYMBOL_CANDIDATES:
        print(f"[hk-snapshot] fetching benchmark: {symbol}")
        try:
            bench_map = client.get_klines_batch(
                [symbol], period="1d", count=count, start_time_ms=start_ms, end_time_ms=end_ms, adjust="forward"
            )
            raw = bench_map.get(symbol)
            norm = normalize_hist_from_fetch(raw) if raw is not None and not raw.empty else None
            if norm is not None and not norm.empty:
                return norm, symbol
        except Exception as e:
            print(f"[hk-snapshot] benchmark fetch failed: {symbol}: {e}")
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
) -> int:
    full_df.to_csv(out_dir / "hist_full.csv.gz", index=False, compression="gzip")
    print(f"[hk-snapshot] hist_full.csv.gz: {len(full_df)} rows")

    if bench_df is not None and not bench_df.empty:
        bench_df.to_csv(out_dir / "benchmark_main.csv", index=False)
        print(f"[hk-snapshot] benchmark_main.csv: {len(bench_df)} rows")
    else:
        print("[hk-snapshot] WARNING: no benchmark data, backtest will fail without trade calendar")
        return 1

    (out_dir / "name_map.json").write_text(json.dumps(name_map, ensure_ascii=False), encoding="utf-8")
    (out_dir / "sector_map.json").write_text("{}", encoding="utf-8")
    (out_dir / "market_cap_map.json").write_text("{}", encoding="utf-8")
    meta = {
        "market": "hk",
        "symbols": len(symbols),
        "ok": ok_count,
        "fail": len(symbols) - ok_count,
        "start": prefetch_start.strftime("%Y%m%d"),
        "end": end_dt.strftime("%Y%m%d"),
        "benchmark": bench_symbol,
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"[hk-snapshot] Done! {ok_count}/{len(symbols)} ({100 * ok_count / len(symbols):.1f}%)")
    return 0


def run_hk_snapshot_fetch(args) -> int:
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        print("[hk-snapshot] ERROR: TICKFLOW_API_KEY not set")
        return 1
    client = TickFlowClient(api_key=api_key)
    start_dt = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(args.end, "%Y-%m-%d").date()
    prefetch_start = start_dt - timedelta(days=int(args.trading_days * 2))
    start_ms = int(datetime.combine(prefetch_start, datetime.min.time()).timestamp() * 1000)
    end_ms = int(datetime.combine(end_dt, datetime.max.time()).timestamp() * 1000)
    count = (end_dt - prefetch_start).days + 50
    print(f"[hk-snapshot] date range: {prefetch_start} -> {end_dt} (count={count})")

    symbols, name_map = load_hk_symbols()
    if not symbols:
        print("[hk-snapshot] ERROR: no HK symbols found in data/market_universes/hk.txt")
        return 1
    if args.max_symbols > 0 and len(symbols) > args.max_symbols:
        symbols = symbols[: args.max_symbols]
    print(f"[hk-snapshot] symbol pool: {len(symbols)} (sample: {symbols[:5]})")

    df_map = _fetch_klines_batched(client, symbols, count, start_ms, end_ms)
    print(f"[hk-snapshot] fetched: {len(df_map)}/{len(symbols)} symbols")
    if len(df_map) < len(symbols) * 0.1:
        print(f"[hk-snapshot] ERROR: success rate {len(df_map)}/{len(symbols)} below 10%")
        return 1

    frames = [
        df.assign(symbol=sym)
        for sym, raw in df_map.items()
        if (df := normalize_hist_from_fetch(raw)) is not None and not df.empty
    ]
    if not frames:
        print("[hk-snapshot] ERROR: no valid data after normalization")
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bench_df, bench_symbol = _fetch_benchmark(client, count, start_ms, end_ms)
    full_df = pd.concat(frames, ignore_index=True)
    return _save_snapshot(
        out_dir, full_df, bench_df, bench_symbol, symbols, len(df_map), name_map, prefetch_start, end_dt
    )
