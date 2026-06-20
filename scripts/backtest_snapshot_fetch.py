#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from core.wyckoff_engine import normalize_hist_from_fetch
from integrations.data_source import fetch_index_hist, fetch_market_cap_map, fetch_sector_map, fetch_stock_hist
from integrations.fetch_a_share_csv import _normalize_symbols, get_stocks_by_board


def _as_yyyymmdd(text: str) -> str:
    return str(text or "").strip().replace("-", "")


def _normalize_board(board: str) -> str:
    b = str(board or "").strip().lower()
    if b in {"", "all", "main_chinext", "main_chinext_star"}:
        return "all"
    return b


def _load_symbols(board: str, sample_size: int) -> tuple[list[str], list[dict]]:
    board_norm = _normalize_board(board)
    raw_pool = get_stocks_by_board(board_norm)
    pool: list[dict] = []
    for item in raw_pool:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        if not code:
            continue
        pool.append({"code": code, "name": name})

    name_map = {
        str(x.get("code", "")).strip(): str(x.get("name", "")).strip() for x in pool if str(x.get("code", "")).strip()
    }
    symbols = [
        s for s in sorted(set(_normalize_symbols(list(name_map.keys())))) if "ST" not in name_map.get(s, "").upper()
    ]
    if sample_size > 0 and sample_size < len(symbols):
        random.seed(42)
        symbols = random.sample(symbols, sample_size)
    filtered_pool = [{"code": s, "name": name_map.get(s, "")} for s in symbols]
    return symbols, filtered_pool


def _fetch_one(
    symbol: str,
    prefetch_start: str,
    end_s: str,
) -> tuple[str, pd.DataFrame | None, str | None, float]:
    t0 = time.monotonic()
    try:
        raw = fetch_stock_hist(symbol, prefetch_start, end_s, adjust="qfq")
        if raw is None or raw.empty:
            return (symbol, None, "no_data", time.monotonic() - t0)
        df = normalize_hist_from_fetch(raw)
        if df is None or df.empty:
            return (symbol, None, "normalized_empty", time.monotonic() - t0)
        df["symbol"] = symbol
        return (symbol, df, None, time.monotonic() - t0)
    except Exception as e:
        return (symbol, None, str(e), time.monotonic() - t0)


def _tickflow_window(prefetch_start: str, end_s: str) -> tuple[int, int, int, str, str]:
    start_d = datetime.strptime(prefetch_start, "%Y%m%d").date()
    end_d = datetime.strptime(end_s, "%Y%m%d").date()
    cn_tz = timezone(timedelta(hours=8))
    start_ms = int(datetime.combine(start_d, datetime.min.time(), tzinfo=cn_tz).timestamp() * 1000)
    end_ms = int(
        (
            datetime.combine(end_d + timedelta(days=1), datetime.min.time(), tzinfo=cn_tz) - timedelta(milliseconds=1)
        ).timestamp()
        * 1000
    )
    day_span = (end_d - start_d).days + 1
    count = min(max(day_span * 2 + 16, 64), 5000)
    return start_ms, end_ms, count, start_d.isoformat(), end_d.isoformat()


def _frame_from_tickflow_batch(
    sym: str,
    raw_df: pd.DataFrame | None,
    start_iso: str,
    end_iso: str,
) -> tuple[pd.DataFrame | None, str | None]:
    if raw_df is None or raw_df.empty:
        return None, "no_data_in_batch"
    out = raw_df[(raw_df["date"] >= start_iso) & (raw_df["date"] <= end_iso)].copy()
    if out.empty:
        return None, "empty_in_range"
    close = pd.to_numeric(out.get("close"), errors="coerce")
    prev_close = pd.to_numeric(out.get("prev_close"), errors="coerce")
    prev_ref = prev_close.where(prev_close > 0)
    if prev_ref.notna().sum() == 0:
        prev_ref = close.shift(1)
    pct = (close / prev_ref - 1.0) * 100.0
    high_s = pd.to_numeric(out.get("high"), errors="coerce")
    low_s = pd.to_numeric(out.get("low"), errors="coerce")
    amp = (high_s - low_s) / prev_ref * 100.0
    result = pd.DataFrame(
        {
            "日期": out["date"].values,
            "开盘": out["open"].values,
            "最高": out["high"].values,
            "最低": out["low"].values,
            "收盘": out["close"].values,
            "成交量": out["volume"].values,
            "成交额": out["amount"].values,
            "涨跌幅": pct.values,
            "换手率": 0.0,
            "振幅": amp.values,
        }
    )
    df = normalize_hist_from_fetch(result)
    if df is None or df.empty:
        return None, "normalized_empty"
    df["symbol"] = sym
    return df, None


def _fetch_batch_tickflow(
    symbols: list[str], prefetch_start: str, end_s: str
) -> tuple[list[pd.DataFrame], int, int, list[str]]:
    """用 TickFlow batch API 批量拉取，减少 API 调用次数。"""
    from integrations.tickflow_client import TickFlowClient, normalize_cn_symbol

    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TICKFLOW_API_KEY 未配置")
    client = TickFlowClient(api_key=api_key)
    start_ms, end_ms, count, start_iso, end_iso = _tickflow_window(prefetch_start, end_s)
    batch_result = client.get_klines_batch(
        symbols,
        period="1d",
        count=count,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        adjust="forward",
    )

    all_frames: list[pd.DataFrame] = []
    fail_samples: list[str] = []
    fail = 0
    for sym in symbols:
        df, error = _frame_from_tickflow_batch(sym, batch_result.get(normalize_cn_symbol(sym)), start_iso, end_iso)
        if error:
            fail += 1
            if len(fail_samples) < 10:
                fail_samples.append(f"{sym}: {error}")
            continue
        all_frames.append(df)
    ok = len(all_frames)
    return all_frames, ok, fail, fail_samples


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest Grid snapshot fetcher")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--board", default="all")
    parser.add_argument("--sample-size", type=int, default=0)
    parser.add_argument("--trading-days", type=int, default=320)
    parser.add_argument("--output-dir", default="snapshot_data")
    parser.add_argument("--max-workers", type=int, default=int(os.getenv("BACKTEST_SNAPSHOT_WORKERS", "6")))
    args = parser.parse_args()

    start_s = _as_yyyymmdd(args.start)
    end_s = _as_yyyymmdd(args.end)
    start_dt = datetime.strptime(start_s, "%Y%m%d").date()
    prefetch_start = (start_dt - timedelta(days=int(args.trading_days * 2))).strftime("%Y%m%d")

    print(f"[snapshot] 数据区间: {prefetch_start} -> {end_s}")

    symbols, raw_pool = _load_symbols(args.board, int(args.sample_size))
    if not symbols:
        print("[snapshot] 严重错误: 股票池为空，请检查 board 参数或行情源可用性")
        return 1
    print(
        f"[snapshot] 股票池: {len(symbols)} symbols, sample={symbols[:5]}, "
        f"board={_normalize_board(args.board)}, exclude_st=True"
    )

    all_frames: list[pd.DataFrame] = []
    ok = 0
    fail = 0
    fail_samples: list[str] = []

    # 优先用 TickFlow batch API（一次请求 200 只，大幅减少 API 调用次数）
    _tf_disabled = os.getenv("DATA_SOURCE_DISABLE_TICKFLOW", "").strip().lower() in {"1", "true", "yes", "on"}
    use_batch = bool(os.getenv("TICKFLOW_API_KEY", "").strip()) and not _tf_disabled

    if use_batch:
        print("[snapshot] fetch模式: TickFlow batch API (每批200只，顺序请求避免限流)")
        try:
            all_frames, ok, fail, fail_samples = _fetch_batch_tickflow(symbols, prefetch_start, end_s)
        except Exception as e:
            print(f"[snapshot] batch 模式失败: {e}，回退逐只并发模式")
            use_batch = False

    if not use_batch:
        workers = max(int(args.max_workers), 1)
        print(f"[snapshot] fetch模式: 逐只并发, workers={workers}")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_fetch_one, sym, prefetch_start, end_s): sym for sym in symbols}
            for done, ft in enumerate(as_completed(futs), 1):
                sym, df, err, elapsed = ft.result()
                if df is not None:
                    all_frames.append(df)
                    ok += 1
                else:
                    fail += 1
                    if len(fail_samples) < 10:
                        fail_samples.append(f"{sym}: {str(err)[:200]} (elapsed={elapsed:.1f}s)")
                if done % 500 == 0 or done == len(futs):
                    print(f"[snapshot] {done}/{len(futs)} (ok={ok}, fail={fail})")

    if fail_samples:
        print("[snapshot] 失败样本:")
        for item in fail_samples[:10]:
            print(f"  - {item}")

    bench_main = None
    try:
        from integrations.data_source import _fetch_index_akshare

        bench_main = _fetch_index_akshare("000001", prefetch_start, end_s)
        print(f"[snapshot] 大盘指数 via akshare: {len(bench_main)} rows")
    except Exception as e1:
        print(f"[snapshot] akshare 大盘失败: {e1}, fallback fetch_index_hist")
        try:
            bench_main = fetch_index_hist("000001", prefetch_start, end_s)
        except Exception as e2:
            print(f"[snapshot] 大盘指数全部失败（不阻塞）: {e2}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not all_frames:
        print("[snapshot] 严重错误: 没有成功拉取任何股票数据!")
        return 1
    if ok < len(symbols) * 0.1:
        print(f"[snapshot] 严重错误: 成功率仅 {ok}/{len(symbols)} ({100 * ok / len(symbols):.1f}%)，低于 10% 阈值")
        return 1

    full_df = pd.concat(all_frames, ignore_index=True)
    full_df.to_csv(out_dir / "hist_full.csv.gz", index=False, compression="gzip")
    print(f"[snapshot] hist_full.csv.gz: {len(full_df)} rows")

    if bench_main is not None and not bench_main.empty:
        bench_main.to_csv(out_dir / "benchmark_main.csv", index=False)
        print(f"[snapshot] benchmark_main.csv: {len(bench_main)} rows")

    name_map: dict[str, str] = {}
    for item in raw_pool:
        if isinstance(item, dict):
            c = str(item.get("code", "")).strip()
            n = str(item.get("name", "")).strip()
            if c:
                name_map[c] = n
    (out_dir / "name_map.json").write_text(json.dumps(name_map, ensure_ascii=False), encoding="utf-8")
    print(f"[snapshot] name_map.json: {len(name_map)} entries")

    try:
        sm = fetch_sector_map()
        (out_dir / "sector_map.json").write_text(json.dumps(sm, ensure_ascii=False), encoding="utf-8")
        print(f"[snapshot] sector_map.json: {len(sm)} entries")
    except Exception as e:
        print(f"[snapshot] sector_map 拉取失败（不阻塞）: {e}")

    try:
        cm = fetch_market_cap_map()
        (out_dir / "market_cap_map.json").write_text(json.dumps(cm, ensure_ascii=False), encoding="utf-8")
        print(f"[snapshot] market_cap_map.json: {len(cm)} entries")
    except Exception as e:
        print(f"[snapshot] market_cap_map 拉取失败（不阻塞）: {e}")

    meta = {
        "symbols": len(symbols),
        "ok": ok,
        "fail": fail,
        "start": prefetch_start,
        "end": end_s,
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"[snapshot] Done! 成功率: {ok}/{len(symbols)} ({100 * ok / len(symbols):.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
