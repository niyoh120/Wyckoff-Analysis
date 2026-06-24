"""Concurrent fallback daily OHLCV fetcher."""

from __future__ import annotations

import logging
import socket
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field, replace

import pandas as pd

from core.hist_dates import latest_trade_date_from_hist
from core.wyckoff_engine import normalize_hist_from_fetch
from tools.spot_patch import append_spot_bar_if_needed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchRuntimeConfig:
    max_retries: int = 2
    retry_base_delay: float = 1.0
    socket_timeout: int = 20
    fetch_timeout: int = 45
    batch_timeout: int = 420
    batch_size: int = 200
    batch_sleep: float = 0.55
    max_workers: int = 8
    executor_mode: str = "process"

    def normalized(self) -> FetchRuntimeConfig:
        return FetchRuntimeConfig(
            max_retries=max(int(self.max_retries), 1),
            retry_base_delay=max(float(self.retry_base_delay), 0.0),
            socket_timeout=max(int(self.socket_timeout), 1),
            fetch_timeout=max(int(self.fetch_timeout), 0),
            batch_timeout=max(int(self.batch_timeout), 1),
            batch_size=max(int(self.batch_size), 1),
            batch_sleep=max(float(self.batch_sleep), 0.0),
            max_workers=max(int(self.max_workers), 1),
            executor_mode=_executor_mode(self.executor_mode),
        )


def _executor_mode(value: str | None) -> str:
    mode = str(value or "process").strip().lower()
    return mode if mode in {"thread", "process"} else "process"


DEFAULT_FETCH_RUNTIME_CONFIG = FetchRuntimeConfig().normalized()
MAX_RETRIES = DEFAULT_FETCH_RUNTIME_CONFIG.max_retries
RETRY_BASE_DELAY = DEFAULT_FETCH_RUNTIME_CONFIG.retry_base_delay
SOCKET_TIMEOUT = DEFAULT_FETCH_RUNTIME_CONFIG.socket_timeout
FETCH_TIMEOUT = DEFAULT_FETCH_RUNTIME_CONFIG.fetch_timeout
BATCH_TIMEOUT = DEFAULT_FETCH_RUNTIME_CONFIG.batch_timeout
BATCH_SIZE = DEFAULT_FETCH_RUNTIME_CONFIG.batch_size
BATCH_SLEEP = DEFAULT_FETCH_RUNTIME_CONFIG.batch_sleep
MAX_WORKERS = DEFAULT_FETCH_RUNTIME_CONFIG.max_workers
EXECUTOR_MODE = DEFAULT_FETCH_RUNTIME_CONFIG.executor_mode


@dataclass
class FetchCounters:
    df_map: dict[str, pd.DataFrame] = field(default_factory=dict)
    fetch_ok: int = 0
    fetch_fail: int = 0
    fetch_date_mismatch: int = 0
    fetch_spot_patched: int = 0


@dataclass
class BatchCounters:
    ok: int = 0
    fail: int = 0


def _normalize_hist(df: pd.DataFrame) -> pd.DataFrame:
    out = normalize_hist_from_fetch(df)
    out.attrs.update(getattr(df, "attrs", {}) or {})
    return out


def _fetch_hist(symbol: str, window, adjust: str, *, direct_source: bool = False) -> pd.DataFrame:
    if direct_source:
        from integrations.data_source import fetch_stock_hist

        df = fetch_stock_hist(
            symbol=symbol,
            start=window.start_trade_date,
            end=window.end_trade_date,
            adjust=adjust,
        )
    else:
        from integrations.fetch_a_share_csv import fetch_hist as _fh

        df = _fh(symbol=symbol, window=window, adjust=adjust)
    return _normalize_hist(df)


def _run_with_timeout(sym: str, window, timeout_s: int, *, direct_source: bool = False) -> pd.DataFrame:
    """
    在 worker 进程内给单票请求加硬超时（Unix 下用 SIGALRM）。
    若平台不支持 SIGALRM（例如 Windows），则退化为直接调用。
    """
    if timeout_s <= 0:
        return _fetch_hist(sym, window, "qfq", direct_source=direct_source)

    try:
        import signal
    except Exception:
        return _fetch_hist(sym, window, "qfq", direct_source=direct_source)

    if not hasattr(signal, "SIGALRM"):
        return _fetch_hist(sym, window, "qfq", direct_source=direct_source)

    def _alarm_handler(signum, frame):  # pragma: no cover - signal handler
        raise TimeoutError(f"single fetch timeout>{timeout_s}s")

    old = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(timeout_s)
    try:
        return _fetch_hist(sym, window, "qfq", direct_source=direct_source)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def fetch_one_with_retry(
    sym: str,
    window,
    config: FetchRuntimeConfig | int | None = None,
    direct_source: bool = False,
    *,
    max_retries: int | None = None,
) -> tuple[str, pd.DataFrame | None]:
    """在子进程中执行，单票硬超时 + 重试，避免个别数据源卡死拖慢整批。"""
    cfg = _resolve_fetch_runtime_config(config, max_retries)
    socket.setdefaulttimeout(cfg.socket_timeout)
    for attempt in range(cfg.max_retries):
        try:
            df = _run_with_timeout(sym, window, cfg.fetch_timeout, direct_source=direct_source)
            return (sym, df)
        except Exception:
            _sleep_before_retry(attempt, cfg)
    return (sym, None)


def fetch_one_with_retry_thread(
    sym: str,
    window,
    config: FetchRuntimeConfig | int | None = None,
    direct_source: bool = False,
    *,
    max_retries: int | None = None,
) -> tuple[str, pd.DataFrame | None]:
    """线程模式：避免 signal，依赖数据源请求超时与重试。"""
    cfg = _resolve_fetch_runtime_config(config, max_retries)
    for attempt in range(cfg.max_retries):
        try:
            df = _fetch_hist(sym, window, "qfq", direct_source=direct_source)
            return (sym, df)
        except Exception:
            _sleep_before_retry(attempt, cfg)
    return (sym, None)


def _sleep_before_retry(attempt: int, config: FetchRuntimeConfig) -> None:
    if attempt < config.max_retries - 1 and config.retry_base_delay > 0:
        time.sleep(config.retry_base_delay * (attempt + 1))


def _resolve_fetch_runtime_config(
    config: FetchRuntimeConfig | int | None, max_retries: int | None
) -> FetchRuntimeConfig:
    if isinstance(config, int):
        return replace(DEFAULT_FETCH_RUNTIME_CONFIG, max_retries=config).normalized()
    cfg = (config or DEFAULT_FETCH_RUNTIME_CONFIG).normalized()
    if max_retries is None:
        return cfg
    return replace(cfg, max_retries=max_retries).normalized()


def terminate_executor_processes(ex: ProcessPoolExecutor, batch_no: int) -> None:
    """批次超时时，主动终止仍存活的子进程。"""
    procs = getattr(ex, "_processes", {}) or {}
    killed = 0
    for proc in procs.values():
        from contextlib import suppress

        with suppress(Exception):
            if proc and proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=1)
                killed += 1
    if killed:
        logger.warning("batch #%s terminated %s stuck child processes", batch_no, killed)


def _record_frame_result(
    sym: str,
    df: pd.DataFrame | None,
    window,
    enforce_target_trade_date: bool,
    counters: FetchCounters,
    batch: BatchCounters,
    batch_no: int,
) -> None:
    if df is None:
        batch.fail += 1
        counters.fetch_fail += 1
        return
    if enforce_target_trade_date:
        df = _align_frame_trade_date(sym, df, window, counters, batch, batch_no)
        if df is None:
            return
    batch.ok += 1
    counters.fetch_ok += 1
    counters.df_map[sym] = df


def _align_frame_trade_date(
    sym: str,
    df: pd.DataFrame,
    window,
    counters: FetchCounters,
    batch: BatchCounters,
    batch_no: int,
) -> pd.DataFrame | None:
    latest_trade = latest_trade_date_from_hist(df)
    if latest_trade == window.end_trade_date:
        return df
    df, patched = append_spot_bar_if_needed(sym, df, window.end_trade_date)
    if patched:
        latest_trade = latest_trade_date_from_hist(df)
        counters.fetch_spot_patched += 1
    if latest_trade == window.end_trade_date:
        return df
    batch.fail += 1
    counters.fetch_fail += 1
    counters.fetch_date_mismatch += 1
    logger.warning(
        "batch #%s skipped %s: latest_trade_date=%s, target_trade_date=%s",
        batch_no,
        sym,
        latest_trade,
        window.end_trade_date,
    )
    return None


def _fetch_batch_frames(
    batch: list[str],
    window,
    *,
    batch_no: int,
    max_workers: int,
    batch_timeout: int,
    executor_mode: str,
    direct_source: bool,
    enforce_target_trade_date: bool,
    config: FetchRuntimeConfig,
    counters: FetchCounters,
) -> BatchCounters:
    batch_counts = BatchCounters()
    use_process = executor_mode == "process"
    executor = (
        ProcessPoolExecutor(max_workers=max_workers) if use_process else ThreadPoolExecutor(max_workers=max_workers)
    )
    fetch_fn = fetch_one_with_retry if use_process else fetch_one_with_retry_thread
    futures = {executor.submit(fetch_fn, s, window, config, direct_source): s for s in batch}
    try:
        for future in as_completed(futures, timeout=batch_timeout):
            _record_future_result(future, futures, window, enforce_target_trade_date, counters, batch_counts, batch_no)
    except FuturesTimeoutError:
        _handle_batch_timeout(futures, batch_no, batch_timeout, batch_counts, counters, use_process, executor)
    finally:
        _shutdown_batch_executor(futures, executor)
    return batch_counts


def _record_future_result(
    future,
    futures: dict,
    window,
    enforce_target_trade_date: bool,
    counters: FetchCounters,
    batch_counts: BatchCounters,
    batch_no: int,
) -> None:
    sym = futures[future]
    try:
        _, df = future.result()
    except Exception as e:
        logger.warning("batch #%s fetch failed %s: %s", batch_no, sym, e)
        batch_counts.fail += 1
        counters.fetch_fail += 1
        return
    _record_frame_result(sym, df, window, enforce_target_trade_date, counters, batch_counts, batch_no)


def _handle_batch_timeout(
    futures: dict,
    batch_no: int,
    batch_timeout: int,
    batch_counts: BatchCounters,
    counters: FetchCounters,
    use_process: bool,
    executor,
) -> None:
    pending_symbols = [futures[ft] for ft in futures if not ft.done()]
    timed_out = len(pending_symbols)
    batch_counts.fail += timed_out
    counters.fetch_fail += timed_out
    logger.warning(
        "batch #%s timeout(%ss): completed=%s/%s, pending=%s, skipping remaining tasks",
        batch_no,
        batch_timeout,
        batch_counts.ok + batch_counts.fail - timed_out,
        len(futures),
        timed_out,
    )
    if pending_symbols:
        preview = ", ".join(pending_symbols[:10])
        suffix = "..." if len(pending_symbols) > 10 else ""
        logger.warning("batch #%s timeout symbols: %s%s", batch_no, preview, suffix)
    if use_process:
        terminate_executor_processes(executor, batch_no)


def _shutdown_batch_executor(futures: dict, executor) -> None:
    for future in futures:
        future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)


def _fetch_stats(counters: FetchCounters, elapsed: float) -> dict[str, int | float]:
    qps = (counters.fetch_ok / elapsed) if elapsed > 0 else 0.0
    return {
        "fetch_ok": counters.fetch_ok,
        "fetch_fail": counters.fetch_fail,
        "fetch_date_mismatch": counters.fetch_date_mismatch,
        "fetch_spot_patched": counters.fetch_spot_patched,
        "fetch_elapsed_s": round(elapsed, 2),
        "fetch_qps": round(qps, 3),
    }


def _finish_fetch_progress(counters: FetchCounters, elapsed: float, window, enforce_target_trade_date: bool) -> None:
    overall_qps = (counters.fetch_ok / elapsed) if elapsed > 0 else 0.0
    logger.info(
        "daily fetch done: ok=%s, fail=%s, elapsed=%.1fs, avg_qps=%.2f",
        counters.fetch_ok,
        counters.fetch_fail,
        elapsed,
        overall_qps,
    )
    from utils.progress import report_progress

    report_progress("拉取完成", f"成功={counters.fetch_ok}, 失败={counters.fetch_fail}", 1.0)
    if enforce_target_trade_date:
        logger.info(
            "trade-date alignment: mismatch=%s, spot_patched=%s, target_trade_date=%s",
            counters.fetch_date_mismatch,
            counters.fetch_spot_patched,
            window.end_trade_date,
        )


def fetch_ohlcv_fallback(
    symbols: list[str],
    window,
    *,
    enforce_target_trade_date: bool,
    batch_size: int,
    max_workers: int,
    batch_timeout: int,
    batch_sleep: float,
    executor_mode: str,
    direct_source: bool,
    runtime_config: FetchRuntimeConfig | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, int | float]]:
    config = (runtime_config or DEFAULT_FETCH_RUNTIME_CONFIG).normalized()
    counters = FetchCounters()
    total_batches = (len(symbols) + batch_size - 1) // batch_size if symbols else 0
    _log_fetch_start(symbols, executor_mode, batch_size, max_workers, batch_timeout, total_batches, config)
    total_fetch_started = time.monotonic()
    for i in range(0, len(symbols), batch_size):
        _run_symbol_batch(
            symbols,
            i,
            window,
            counters=counters,
            total_batches=total_batches,
            batch_size=batch_size,
            max_workers=max_workers,
            batch_timeout=batch_timeout,
            batch_sleep=batch_sleep,
            executor_mode=executor_mode,
            direct_source=direct_source,
            enforce_target_trade_date=enforce_target_trade_date,
            config=config,
        )
    elapsed = time.monotonic() - total_fetch_started
    _finish_fetch_progress(counters, elapsed, window, enforce_target_trade_date)
    return counters.df_map, _fetch_stats(counters, elapsed)


def _log_fetch_start(
    symbols: list[str],
    executor_mode: str,
    batch_size: int,
    max_workers: int,
    batch_timeout: int,
    total_batches: int,
    config: FetchRuntimeConfig,
) -> None:
    logger.info(
        "daily fetch start: symbols=%s, executor=%s, batch_size=%s, max_workers=%s, batch_timeout=%ss, fetch_timeout=%ss, retries=%s",
        len(symbols),
        executor_mode,
        batch_size,
        max_workers,
        batch_timeout,
        config.fetch_timeout,
        config.max_retries,
    )
    from utils.progress import report_progress

    report_progress("拉取日线", f"共{len(symbols)}只, {total_batches}批", 0.0)


def _run_symbol_batch(
    symbols: list[str],
    index: int,
    window,
    *,
    counters: FetchCounters,
    total_batches: int,
    batch_size: int,
    max_workers: int,
    batch_timeout: int,
    batch_sleep: float,
    executor_mode: str,
    direct_source: bool,
    enforce_target_trade_date: bool,
    config: FetchRuntimeConfig,
) -> None:
    batch_no = index // batch_size + 1
    batch = symbols[index : index + batch_size]
    batch_started = time.monotonic()
    logger.info("batch #%s/%s start: symbols=%s", batch_no, total_batches, len(batch))
    batch_counts = _fetch_batch_frames(
        batch,
        window,
        batch_no=batch_no,
        max_workers=max_workers,
        batch_timeout=batch_timeout,
        executor_mode=executor_mode,
        direct_source=direct_source,
        enforce_target_trade_date=enforce_target_trade_date,
        config=config,
        counters=counters,
    )
    _log_batch_done(batch_no, total_batches, batch_counts, counters, batch_started)
    if index + batch_size < len(symbols) and batch_sleep > 0:
        time.sleep(batch_sleep)


def _log_batch_done(
    batch_no: int,
    total_batches: int,
    batch_counts: BatchCounters,
    counters: FetchCounters,
    batch_started: float,
) -> None:
    batch_elapsed = time.monotonic() - batch_started
    batch_qps = (batch_counts.ok / batch_elapsed) if batch_elapsed > 0 else 0.0
    logger.info(
        "batch #%s done: ok=%s, fail=%s, elapsed=%.1fs, qps=%.2f, total_ok=%s, total_fail=%s",
        batch_no,
        batch_counts.ok,
        batch_counts.fail,
        batch_elapsed,
        batch_qps,
        counters.fetch_ok,
        counters.fetch_fail,
    )
    from utils.progress import report_progress

    report_progress("拉取日线", f"批次#{batch_no}/{total_batches}", batch_no / total_batches)
