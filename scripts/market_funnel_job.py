"""CLI entrypoint for HK/US market funnel jobs."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.market_funnel_job import MARKET_CHOICES, run_market_funnel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TickFlow HK/US Wyckoff funnel job.")
    parser.add_argument("--market", choices=MARKET_CHOICES, required=True)
    parser.add_argument("--output", default="", help="Optional JSON result path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_market_funnel(args.market, output=args.output or None)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
