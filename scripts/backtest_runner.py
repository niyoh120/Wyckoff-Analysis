"""CLI entrypoint for the Wyckoff backtest runner."""

from __future__ import annotations

import logging

import _bootstrap  # noqa: F401

from workflows.backtest_cli import build_backtest_parser
from workflows.backtest_runner import run_backtest_runner


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
    return run_backtest_runner(build_backtest_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
