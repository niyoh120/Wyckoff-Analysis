"""CLI entrypoint for US backtest snapshot fetching."""

from __future__ import annotations

import argparse
import os

import _bootstrap  # noqa: F401

from workflows.backtest_snapshot_fetch_hk_us import run_snapshot_fetch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="US stock backtest snapshot fetcher (TickFlow)")
    parser.add_argument("--start", required=True, help="Backtest start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Backtest end date YYYY-MM-DD")
    parser.add_argument("--trading-days", type=int, default=320, help="Lookback window in trading days")
    parser.add_argument("--output-dir", default="snapshot_data")
    parser.add_argument("--max-symbols", type=int, default=int(os.getenv("BACKTEST_US_MAX_SYMBOLS", "0")))
    return parser.parse_args()


def main() -> int:
    return run_snapshot_fetch(parse_args(), market="us")


if __name__ == "__main__":
    raise SystemExit(main())
