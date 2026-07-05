"""CLI entrypoint for strategy attribution reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflows.strategy_attribution_report import (
    StrategyAttributionRequest,
    build_console_summary,
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
    parser.add_argument(
        "--backtest-confirmation-json",
        default="",
        help="Optional JSON file with structured backtest confirmation for policy promotion gates.",
    )
    parser.add_argument(
        "--formal-dynamic-approval-json",
        default="",
        help="Optional JSON file with manual approval for formal dynamic promotion.",
    )
    return parser.parse_args()


def request_from_args(args: argparse.Namespace) -> StrategyAttributionRequest:
    return StrategyAttributionRequest(
        market=args.market,
        days=args.days,
        horizons=parse_horizons(args.horizons),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        no_write=args.no_write,
        backtest_confirmation_json=load_json_object(args.backtest_confirmation_json, "--backtest-confirmation-json"),
        formal_dynamic_approval_json=load_json_object(
            args.formal_dynamic_approval_json, "--formal-dynamic-approval-json"
        ),
    )


def load_backtest_confirmation(path: str) -> dict[str, object] | None:
    return load_json_object(path, "--backtest-confirmation-json")


def load_json_object(path: str, flag: str) -> dict[str, object] | None:
    if not str(path or "").strip():
        return None
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{flag} must point to a JSON object")
    return data


def main() -> int:
    args = parse_args()
    report = run_strategy_attribution_report(request_from_args(args))
    print(json.dumps(build_console_summary(report, written=not args.no_write), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
