"""CLI entrypoint for the daily Wyckoff job."""

from __future__ import annotations

import argparse
import logging

import _bootstrap  # noqa: F401

from workflows.daily_job import run_daily_job

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每日定时任务：Wyckoff Funnel -> 批量研报")
    parser.add_argument("--dry-run", action="store_true", help="仅校验配置，不执行任务")
    parser.add_argument("--logs", default=None, help="日志文件路径，默认 logs/daily_job_YYYYMMDD_HHMMSS.log")
    return parser.parse_args()


def main() -> int:
    return run_daily_job(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
