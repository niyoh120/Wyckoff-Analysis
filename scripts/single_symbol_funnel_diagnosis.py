"""CLI entrypoint for single-symbol funnel replay diagnosis."""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401

from workflows.single_symbol_diagnosis import SingleSymbolDiagnosisRequest, run_single_symbol_diagnosis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="单只股票漏斗逐日复盘诊断")
    parser.add_argument("--symbol", required=True, help="股票代码，逗号分隔可批量，同一市场，如 002980,301511,301018")
    parser.add_argument("--start-date", required=True, help="回看起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="回看结束日期 YYYY-MM-DD")
    parser.add_argument("--trading-days", type=int, default=320, help="起始日前置交易日数量")
    parser.add_argument("--output-dir", default="logs/single_symbol_funnel", help="输出目录")
    parser.add_argument("--skip-rps-universe", action="store_true", help="跳过全市场 RPS 计算（快速模式，RPS 不准确）")
    return parser


def request_from_args(args: argparse.Namespace) -> SingleSymbolDiagnosisRequest:
    return SingleSymbolDiagnosisRequest(
        symbol=args.symbol,
        start_date=args.start_date,
        end_date=args.end_date,
        trading_days=args.trading_days,
        output_dir=Path(args.output_dir),
        skip_rps_universe=args.skip_rps_universe,
    )


def main() -> int:
    return run_single_symbol_diagnosis(request_from_args(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
