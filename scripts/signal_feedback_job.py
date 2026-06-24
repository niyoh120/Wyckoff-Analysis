"""CLI entrypoint for signal feedback refresh."""

from __future__ import annotations

import argparse
from datetime import date

from workflows.signal_feedback_job import (
    SignalFeedbackConfig,
    default_registry_horizon,
    parse_horizons,
    run_signal_feedback,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Wyckoff signal feedback tables.")
    parser.add_argument("--market", default="cn")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--horizons", type=parse_horizons, default=parse_horizons("1,3,5,10,20"))
    parser.add_argument("--observation-days", type=int, default=120)
    parser.add_argument("--outcome-days", type=int, default=180)
    parser.add_argument("--pre-days", type=int, default=10)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--outcome-limit", type=int, default=20000)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--registry-horizon", type=int, default=default_registry_horizon())
    parser.add_argument("--health-only", action="store_true")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> SignalFeedbackConfig:
    return SignalFeedbackConfig(
        market=args.market,
        end_date=args.end_date,
        as_of_date=args.as_of_date,
        horizons=args.horizons,
        observation_days=args.observation_days,
        outcome_days=args.outcome_days,
        pre_days=args.pre_days,
        limit=args.limit,
        outcome_limit=args.outcome_limit,
        min_samples=args.min_samples,
        registry_horizon=args.registry_horizon,
        health_only=args.health_only,
    )


def main() -> int:
    run_signal_feedback(config_from_args(parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
