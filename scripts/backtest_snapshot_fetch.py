"""CLI entrypoint for A-share backtest snapshot fetching."""

from __future__ import annotations

import argparse
import os

import _bootstrap  # noqa: F401

from workflows.backtest_snapshot_fetch import run_snapshot_fetch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest Grid snapshot fetcher")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--board", default="all")
    parser.add_argument("--sample-size", type=int, default=0)
    parser.add_argument("--trading-days", type=int, default=320)
    parser.add_argument("--output-dir", default="snapshot_data")
    parser.add_argument("--max-workers", type=int, default=int(os.getenv("BACKTEST_SNAPSHOT_WORKERS", "6")))
    return parser.parse_args()


def main() -> int:
    return run_snapshot_fetch(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
