"""CLI entrypoint for US recommendation performance refresh."""

from __future__ import annotations

import argparse
import os

import _bootstrap  # noqa: F401

from workflows.us_recommendation_performance_job import (
    UsRecommendationPerformanceRequest,
    run_us_recommendation_performance_job,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh US recommendation MFE/MAE/range metrics.")
    parser.add_argument("--logs", default="", help="日志文件路径（可选）")
    parser.add_argument("--max-dates", type=int, default=int(os.getenv("US_TRACKING_PERFORMANCE_MAX_DATES", "60")))
    parser.add_argument("--kline-count", type=int, default=int(os.getenv("US_TRACKING_PERFORMANCE_KLINE_COUNT", "160")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_us_recommendation_performance_job(
        UsRecommendationPerformanceRequest(
            logs_path=args.logs,
            max_dates=args.max_dates,
            kline_count=args.kline_count,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
