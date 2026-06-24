"""CLI entrypoint for web-triggered background jobs."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.web_background_job import run_web_background_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub Actions 后台量化作业")
    parser.add_argument("--job-kind", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--payload-json", default="")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    return run_web_background_job(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
