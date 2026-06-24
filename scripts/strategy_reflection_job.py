"""CLI entrypoint for strategy reflection refresh."""

from __future__ import annotations

import argparse
import os
from datetime import date

from workflows.strategy_reflection_job import StrategyReflectionRequest, run_strategy_reflection_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh strategy reflection shadow artifacts.")
    parser.add_argument("--market", default="cn")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--horizon-days", type=int, default=int(os.getenv("SIGNAL_REGISTRY_HORIZON", "5")))
    parser.add_argument("--outcome-days", type=int, default=180)
    parser.add_argument("--shadow-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def request_from_args(args: argparse.Namespace) -> StrategyReflectionRequest:
    return StrategyReflectionRequest(
        market=args.market,
        as_of_date=args.as_of_date,
        horizon_days=args.horizon_days,
        outcome_days=args.outcome_days,
        shadow_days=args.shadow_days,
        limit=args.limit,
        dry_run=args.dry_run,
    )


def main() -> int:
    return run_strategy_reflection_job(request_from_args(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
