"""Benchmark A-share funnel OHLCV fetch paths."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from core.wyckoff_engine import normalize_hist_from_fetch
from integrations.fetch_a_share_csv import get_stocks_by_board, normalize_symbols, resolve_trading_window
from utils.trading_clock import resolve_end_calendar_day


@dataclass(frozen=True)
class BenchmarkFetchConfig:
    symbols: tuple[str, ...] = ()
    sample: int = 200
    workers: int = 4
    mode: str = "thread"
    runner: str = "batch"
    path: str = "compare"
    trading_days: int = 320
    batch_size: int = 200
    batch_timeout: int = 420
    batch_sleep: float = 0.55
    disable_tickflow_batch: bool = False
    enforce_target_date: bool = False
    output: Path | None = None


LogFn = Callable[[str], None]


def run_benchmark_funnel_fetch(config: BenchmarkFetchConfig, log_fn: LogFn = print) -> list[dict]:
    symbols = resolve_benchmark_symbols(config.symbols, config.sample)
    if not symbols:
        raise ValueError("无有效股票代码")
    window = resolve_trading_window(resolve_end_calendar_day(), max(config.trading_days, 30))
    log_fn(
        f"[bench] runner={config.runner}, mode={config.mode}, workers={config.workers}, "
        f"symbols={len(symbols)}, window={window.start_trade_date}->{window.end_trade_date}, "
        f"disable_tickflow_batch={config.disable_tickflow_batch}"
    )
    summaries = _run_requested_paths(symbols, window, config, log_fn)
    if config.output:
        _write_summary_json(config.output, summaries)
    return summaries


def resolve_benchmark_symbols(symbols: tuple[str, ...], sample: int) -> list[str]:
    if symbols:
        return normalize_symbols(symbols)
    return build_universe(sample)


def build_universe(sample: int) -> list[str]:
    main = [str(x.get("code", "")).strip() for x in get_stocks_by_board("main")]
    chinext = [str(x.get("code", "")).strip() for x in get_stocks_by_board("chinext")]
    star = [str(x.get("code", "")).strip() for x in get_stocks_by_board("star")]
    merged = normalize_symbols(main + chinext + star)
    if sample <= 0 or sample >= len(merged):
        return merged
    step = len(merged) / max(sample, 1)
    return [merged[min(int(i * step), len(merged) - 1)] for i in range(sample)]


def summarize_fetch_rows(
    label: str, symbols: list[str], rows: list[dict[str, Any]], elapsed: float, target_date: str
) -> dict:
    ok = sum(1 for row in rows if row.get("ok"))
    aligned = sum(1 for row in rows if row.get("ok") and row.get("latest") == target_date)
    return {
        "path": label,
        "symbols": len(symbols),
        "ok": ok,
        "fail": len(symbols) - ok,
        "success_pct": round(ok / len(symbols) * 100, 2) if symbols else 0.0,
        "aligned": aligned,
        "aligned_pct": round(aligned / len(symbols) * 100, 2) if symbols else 0.0,
        "elapsed_s": round(elapsed, 2),
        "avg_ms": round(elapsed / len(symbols) * 1000, 1) if symbols else 0.0,
        "qps": round(ok / elapsed, 3) if elapsed > 0 else 0.0,
        "sources": dict(Counter(str(row.get("source", "") or "unknown") for row in rows if row.get("ok"))),
        "errors": dict(Counter(str(row.get("error", "") or "-") for row in rows if not row.get("ok"))),
    }


def _run_requested_paths(symbols: list[str], window, config: BenchmarkFetchConfig, log_fn: LogFn) -> list[dict]:
    if config.path == "compare":
        return [
            _run_path("batch", symbols, window, config, log_fn, runner_override="batch"),
            _run_path("single", symbols, window, config, log_fn, runner_override="single"),
        ]
    return [_run_path(config.path, symbols, window, config, log_fn, runner_override=config.path)]


def _latest_date(df: pd.DataFrame | None) -> str:
    if df is None or df.empty or "date" not in df.columns:
        return ""
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    return dates.iloc[-1].date().isoformat() if not dates.empty else ""


def _fetch_one(symbol: str, window) -> dict[str, Any]:
    try:
        from integrations.data_source import fetch_stock_hist

        raw = fetch_stock_hist(symbol=symbol, start=window.start_trade_date, end=window.end_trade_date, adjust="qfq")
        df = normalize_hist_from_fetch(raw)
        return {
            "symbol": symbol,
            "ok": bool(df is not None and not df.empty),
            "latest": _latest_date(df),
            "source": str(raw.attrs.get("source", "") or ""),
            "upstream_source": str(raw.attrs.get("upstream_source", "") or ""),
        }
    except Exception as e:
        return {"symbol": symbol, "ok": False, "error": type(e).__name__}


def _run_single(symbols: list[str], window, config: BenchmarkFetchConfig) -> tuple[list[dict[str, Any]], float]:
    started = time.monotonic()
    if config.mode == "serial":
        return [_fetch_one(sym, window) for sym in symbols], time.monotonic() - started
    executor_cls = ProcessPoolExecutor if config.mode == "process" else ThreadPoolExecutor
    with executor_cls(max_workers=max(config.workers, 1)) as executor:
        futures = [executor.submit(_fetch_one, sym, window) for sym in symbols]
        rows = [future.result() for future in as_completed(futures)]
    return rows, time.monotonic() - started


def _run_batch(symbols: list[str], window, config: BenchmarkFetchConfig) -> tuple[list[dict[str, Any]], float, dict]:
    import tools.data_fetcher as dfetcher
    import tools.tickflow_batch_fetcher as tickflow_batch_fetcher
    from workflows.fetch_runtime_config import fetch_runtime_config_from_env

    if config.disable_tickflow_batch:
        tickflow_batch_fetcher.TICKFLOW_BATCH_ENABLED = False
    started = time.monotonic()
    df_map, stats = dfetcher.fetch_all_ohlcv(
        symbols=symbols,
        window=window,
        enforce_target_trade_date=config.enforce_target_date,
        batch_size=config.batch_size,
        max_workers=config.workers,
        batch_timeout=config.batch_timeout,
        batch_sleep=config.batch_sleep,
        executor_mode=config.mode if config.mode != "serial" else "thread",
        runtime_config=fetch_runtime_config_from_env(),
    )
    return _batch_rows(symbols, df_map), time.monotonic() - started, stats


def _batch_rows(symbols: list[str], df_map: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": sym,
            "ok": sym in df_map and df_map[sym] is not None and not df_map[sym].empty,
            "latest": _latest_date(df_map.get(sym)),
            "source": str((df_map.get(sym).attrs if sym in df_map else {}).get("source", "") or ""),
        }
        for sym in symbols
    ]


def _run_path(
    label: str,
    symbols: list[str],
    window,
    config: BenchmarkFetchConfig,
    log_fn: LogFn,
    *,
    runner_override: str = "",
) -> dict:
    runner = runner_override or config.runner
    log_fn(f"[bench] start path={label}, runner={runner}, symbols={len(symbols)}")
    rows, elapsed, stats = _execute_runner(runner, symbols, window, config)
    summary = summarize_fetch_rows(label, symbols, rows, elapsed, window.end_trade_date.isoformat())
    summary["fetch_stats"] = stats
    _log_path_summary(label, summary, log_fn)
    return summary


def _execute_runner(
    runner: str, symbols: list[str], window, config: BenchmarkFetchConfig
) -> tuple[list[dict[str, Any]], float, dict]:
    if runner == "batch":
        return _run_batch(symbols, window, config)
    rows, elapsed = _run_single(symbols, window, config)
    return rows, elapsed, {}


def _log_path_summary(label: str, summary: dict, log_fn: LogFn) -> None:
    log_fn(
        f"[bench] {label}: ok={summary['ok']}/{summary['symbols']} "
        f"success={summary['success_pct']}% aligned={summary['aligned_pct']}% "
        f"elapsed={summary['elapsed_s']}s avg={summary['avg_ms']}ms qps={summary['qps']}"
    )
    log_fn(f"[bench] {label}: sources={summary['sources']}")
    if summary["errors"]:
        log_fn(f"[bench] {label}: errors={summary['errors']}")


def _write_summary_json(output: Path, summaries: list[dict]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
