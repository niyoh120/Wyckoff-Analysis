"""CLI entrypoint for the Tail Buy intraday job."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.tail_buy_intraday_job import (
    TailBuyJobRequest,
    default_tail_buy_job_portfolio_id,
    run_tail_buy_intraday_job,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tail Buy intraday job")
    parser.add_argument("--max-llm-symbols", type=int, default=8)
    parser.add_argument("--deadline-minute", type=int, default=56)
    parser.add_argument("--portfolio-id", default=default_tail_buy_job_portfolio_id())
    parser.add_argument("--logs", default=None)
    parser.add_argument("--user-id", default="")
    parser.add_argument(
        "--mode",
        choices=("auto", "intraday", "post_close_review"),
        default="auto",
        help="auto=按交易阶段自动切换；intraday=盘中尾盘执行确认；post_close_review=盘后明日计划复核",
    )
    return parser.parse_args()


def request_from_args(args: argparse.Namespace) -> TailBuyJobRequest:
    return TailBuyJobRequest(
        max_llm_symbols=args.max_llm_symbols,
        deadline_minute=args.deadline_minute,
        portfolio_id=args.portfolio_id,
        logs=args.logs,
        user_id=args.user_id,
        mode=args.mode,
    )


def main() -> int:
    return run_tail_buy_intraday_job(request_from_args(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
