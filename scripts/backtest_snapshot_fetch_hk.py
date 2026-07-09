"""CLI entrypoint for HK backtest snapshot fetch."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.backtest_snapshot_fetch_hk_us import run_snapshot_fetch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch HK backtest data snapshot from TickFlow.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--trading-days", type=int, default=320)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    return run_snapshot_fetch(parse_args(), market="hk")


if __name__ == "__main__":
    raise SystemExit(main())
