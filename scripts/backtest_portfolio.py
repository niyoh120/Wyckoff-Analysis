"""CLI entrypoint for portfolio-level backtests."""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401

from workflows.backtest_portfolio import PortfolioBacktestRequest, run_portfolio_backtest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="组合级回测")
    parser.add_argument("--trades", required=True, help="backtest_runner 输出的 trades CSV")
    parser.add_argument("--output-dir", default="analysis/portfolio")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--max-concurrent", type=int, default=5, help="最大同时持仓数")
    parser.add_argument("--weight-mode", choices=["equal", "score"], default="equal")
    return parser.parse_args()


def request_from_args(args: argparse.Namespace) -> PortfolioBacktestRequest:
    return PortfolioBacktestRequest(
        trades_path=Path(args.trades),
        output_dir=Path(args.output_dir),
        initial_capital=args.initial_capital,
        max_concurrent=args.max_concurrent,
        weight_mode=args.weight_mode,
    )


def main() -> int:
    result = run_portfolio_backtest(request_from_args(parse_args()))
    print(f"[portfolio] trades={result.trades_count}, days={result.trading_days}")
    print(f"[portfolio] NAV -> {result.nav_path}")
    print(f"[portfolio] MD  -> {result.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
