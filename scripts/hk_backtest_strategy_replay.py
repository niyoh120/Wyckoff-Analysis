"""CLI entrypoint for HK backtest strategy replay."""

from __future__ import annotations

import argparse

from workflows.backtest_strategy_replay import run_strategy_replay


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay HK backtest trades with six explicit strategy rules.")
    parser.add_argument("--trades-csv", default="")
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--period-key", required=True)
    parser.add_argument("--period-label", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--top-n", default="2")
    return parser.parse_args()


def main() -> int:
    return run_strategy_replay(parse_args(), market="hk")


if __name__ == "__main__":
    raise SystemExit(main())
