"""CLI entrypoint for benchmark funnel fetch paths."""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401

from workflows.benchmark_funnel_fetch import BenchmarkFetchConfig, run_benchmark_funnel_fetch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wyckoff Funnel 行情取数基准测试")
    parser.add_argument("--symbols", default="", help="逗号分隔股票代码，优先使用")
    parser.add_argument("--sample", type=int, default=200, help="未指定 symbols 时取样；0 表示全量")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--mode", choices=["serial", "thread", "process"], default="thread")
    parser.add_argument("--runner", choices=["batch", "single"], default="batch")
    parser.add_argument("--path", choices=["batch", "single", "compare"], default="compare")
    parser.add_argument("--trading-days", type=int, default=320)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--batch-timeout", type=int, default=420)
    parser.add_argument("--batch-sleep", type=float, default=0.55)
    parser.add_argument("--disable-tickflow-batch", action="store_true")
    parser.add_argument("--enforce-target-date", action="store_true")
    parser.add_argument("--output", default="", help="可选 JSON 输出路径")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> BenchmarkFetchConfig:
    symbols = tuple(x.strip() for x in str(args.symbols).split(",") if x.strip())
    return BenchmarkFetchConfig(
        symbols=symbols,
        sample=args.sample,
        workers=args.workers,
        mode=args.mode,
        runner=args.runner,
        path=args.path,
        trading_days=args.trading_days,
        batch_size=args.batch_size,
        batch_timeout=args.batch_timeout,
        batch_sleep=args.batch_sleep,
        disable_tickflow_batch=args.disable_tickflow_batch,
        enforce_target_date=args.enforce_target_date,
        output=Path(args.output) if args.output else None,
    )


def main() -> int:
    run_benchmark_funnel_fetch(config_from_args(parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
