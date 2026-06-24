"""Filesystem snapshot writer for funnel fetch results."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.hist_dates import latest_trade_date_from_hist
from utils.trading_clock import CN_TZ

logger = logging.getLogger(__name__)


def dump_full_fetch_snapshot(
    *,
    enabled: bool,
    export_dir: str,
    df_map: dict[str, pd.DataFrame],
    all_symbols: list[str],
    window: Any,
    fetch_stats: dict,
    bench_df: pd.DataFrame | None = None,
    smallcap_df: pd.DataFrame | None = None,
) -> str | None:
    if not enabled or not all_symbols:
        return None
    try:
        base_dir = Path(export_dir)
        run_dir = _prepare_run_dir(base_dir)
        full_df, status_rows = _write_hist_files(run_dir, df_map, all_symbols)
        has_bench_main = _write_benchmark(run_dir, bench_df, "benchmark_main.csv")
        has_bench_smallcap = _write_benchmark(run_dir, smallcap_df, "benchmark_smallcap.csv")
        metadata = _write_metadata(
            run_dir, window, all_symbols, status_rows, full_df, fetch_stats, has_bench_main, has_bench_smallcap
        )
        _write_latest_run(base_dir, run_dir)
        logger.info(
            "[funnel] 全量快照已落盘: %s (symbols=%s/%s, rows=%s)",
            run_dir,
            metadata["symbols_fetched"],
            metadata["symbols_total"],
            metadata["rows_total"],
        )
        return str(run_dir)
    except Exception as exc:
        logger.error("全量快照落盘失败: %s", exc, exc_info=True)
        return None


def _prepare_run_dir(base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    run_dir = base_dir / f"full_fetch_{datetime.now(CN_TZ).strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_hist_files(
    run_dir: Path,
    df_map: dict[str, pd.DataFrame],
    all_symbols: list[str],
) -> tuple[pd.DataFrame, list[dict]]:
    frames: list[pd.DataFrame] = []
    status_rows: list[dict] = []
    for symbol in all_symbols:
        row, frame = _symbol_snapshot(symbol, df_map.get(symbol))
        status_rows.append(row)
        if frame is not None:
            frames.append(frame)
    full_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    full_df.to_csv(run_dir / "hist_full.csv.gz", index=False, compression="gzip")
    _latest_quotes(full_df).to_csv(run_dir / "latest_quotes.csv", index=False)
    pd.DataFrame(status_rows).sort_values("symbol").reset_index(drop=True).to_csv(
        run_dir / "fetch_status.csv", index=False
    )
    return full_df, status_rows


def _symbol_snapshot(symbol: str, df: pd.DataFrame | None) -> tuple[dict, pd.DataFrame | None]:
    if df is None or df.empty:
        return {"symbol": symbol, "fetched": 0, "rows": 0, "latest_trade_date": ""}, None
    frame = df.copy()
    frame.insert(0, "symbol", symbol)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    latest_trade_date = latest_trade_date_from_hist(df)
    row = {
        "symbol": symbol,
        "fetched": 1,
        "rows": int(len(df)),
        "latest_trade_date": latest_trade_date.isoformat() if latest_trade_date else "",
    }
    return row, frame


def _latest_quotes(full_df: pd.DataFrame) -> pd.DataFrame:
    if full_df.empty or not {"symbol", "date"}.issubset(full_df.columns):
        return pd.DataFrame(columns=["symbol"])
    return (
        full_df.sort_values(["symbol", "date"])
        .groupby("symbol", as_index=False)
        .tail(1)
        .sort_values("symbol")
        .reset_index(drop=True)
    )


def _write_benchmark(run_dir: Path, df_src: pd.DataFrame | None, filename: str) -> bool:
    if df_src is None or df_src.empty:
        return False
    cols = [c for c in ["date", "open", "high", "low", "close", "volume", "pct_chg"] if c in df_src.columns]
    if not cols:
        return False
    out = df_src[cols].copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out.to_csv(run_dir / filename, index=False)
    return True


def _write_metadata(
    run_dir: Path,
    window: Any,
    all_symbols: list[str],
    status_rows: list[dict],
    full_df: pd.DataFrame,
    fetch_stats: dict,
    has_bench_main: bool,
    has_bench_smallcap: bool,
) -> dict:
    metadata = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "export_dir": str(run_dir),
        "window_start_trade_date": window.start_trade_date.isoformat(),
        "window_end_trade_date": window.end_trade_date.isoformat(),
        "symbols_total": int(len(all_symbols)),
        "symbols_fetched": int(sum(1 for row in status_rows if row["fetched"] == 1)),
        "rows_total": int(len(full_df)),
        "fetch_stats": fetch_stats,
        "has_benchmark_main": has_bench_main,
        "has_benchmark_smallcap": has_bench_smallcap,
    }
    with open(run_dir / "metadata.json", "w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)
    return metadata


def _write_latest_run(base_dir: Path, run_dir: Path) -> None:
    with open(base_dir / "latest_run.txt", "w", encoding="utf-8") as file:
        file.write(str(run_dir) + "\n")
