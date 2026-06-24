"""CLI entrypoint for recommendation tracking price refresh."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.recommendation_tracking_reprice_job import (
    RecommendationRepriceRequest,
    run_recommendation_reprice_job,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="形态复盘价格回填任务（Tickflow 实时报价）")
    parser.add_argument("--logs", default="", help="日志文件路径（可选）")
    parser.add_argument("--market", default="cn", choices=["cn", "us", "hk"], help="市场（默认 cn）")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_recommendation_reprice_job(RecommendationRepriceRequest(logs_path=args.logs, market=args.market))


if __name__ == "__main__":
    raise SystemExit(main())
