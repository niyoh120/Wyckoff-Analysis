"""CLI entrypoint for Wyckoff parameter sensitivity analysis."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.param_sensitivity import ParamSensitivityRequest, run_param_sensitivity_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wyckoff 参数敏感性分析")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--board", default="all")
    parser.add_argument("--sample-size", type=int, default=300)
    parser.add_argument("--trading-days", type=int, default=320)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--snapshot-dir", default="")
    parser.add_argument("--output-dir", default="analysis/sensitivity")
    parser.add_argument("--exit-mode", default="sltp", choices=["close_only", "sltp"])
    return parser.parse_args()


def request_from_args(args: argparse.Namespace) -> ParamSensitivityRequest:
    return ParamSensitivityRequest(
        start=args.start,
        end=args.end,
        board=args.board,
        sample_size=args.sample_size,
        trading_days=args.trading_days,
        workers=args.workers,
        snapshot_dir=args.snapshot_dir,
        output_dir=args.output_dir,
        exit_mode=args.exit_mode,
    )


def main() -> int:
    return run_param_sensitivity_request(request_from_args(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
