from __future__ import annotations

import argparse
import logging

import _bootstrap  # noqa: F401

from workflows.export_a_share_csv import ExportAShareCsvRequest, run_export_a_share_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="拉取 A 股指定股票近 N 个交易日数据，并输出 hist_data 与 ohlcv 两个 CSV 文件。"
    )
    parser.add_argument("--symbol", help="单个股票代码，如 300364")
    parser.add_argument("--symbols", nargs="*", help="多个股票代码，如 000973 600798 300459")
    parser.add_argument("--symbols-text", help='从一段文本中提取股票代码，如 "000973 佛塑科技 600798鲁抗医药"')
    parser.add_argument("--trading-days", type=int, default=320, help="交易日数量，默认 320")
    parser.add_argument("--end-offset-days", type=int, default=1, help="结束日期偏移（自然日），默认 1")
    parser.add_argument("--adjust", default="", choices=["", "qfq", "hfq"], help="复权类型")
    parser.add_argument("--out-dir", default="data", help="输出目录，默认 data 目录")
    return parser


def request_from_args(args: argparse.Namespace) -> ExportAShareCsvRequest:
    return ExportAShareCsvRequest(
        symbol=args.symbol or "",
        symbols=tuple(args.symbols or ()),
        symbols_text=args.symbols_text or "",
        trading_days=int(args.trading_days),
        end_offset_days=int(args.end_offset_days),
        adjust=str(args.adjust),
        out_dir=str(args.out_dir),
    )


def main() -> int:
    return run_export_a_share_csv(request_from_args(build_parser().parse_args()))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
