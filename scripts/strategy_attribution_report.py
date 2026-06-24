"""CLI entrypoint for strategy attribution reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflows.strategy_attribution_report import (
    StrategyAttributionRequest,
    parse_horizons,
    run_strategy_attribution_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build strategy attribution report")
    parser.add_argument("--market", default="cn")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def request_from_args(args: argparse.Namespace) -> StrategyAttributionRequest:
    return StrategyAttributionRequest(
        market=args.market,
        days=args.days,
        horizons=parse_horizons(args.horizons),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        no_write=args.no_write,
    )


def main() -> int:
    args = parse_args()
    report = run_strategy_attribution_report(request_from_args(args))
    print(json.dumps({"market": args.market, "report_date": report["report_date"], "written": not args.no_write}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
