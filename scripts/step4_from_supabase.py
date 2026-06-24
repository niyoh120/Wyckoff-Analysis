"""CLI entrypoint for running Step4 from Supabase rows."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.step4_from_supabase import Step4FromSupabaseRequest, run_step4_from_supabase


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Step4 from Supabase recommendation_tracking")
    parser.add_argument("--recommend-date", default="", help="YYYYMMDD or YYYY-MM-DD; defaults to latest trade date")
    parser.add_argument("--logs", default="", help="Log file path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_step4_from_supabase(Step4FromSupabaseRequest(recommend_date=args.recommend_date, logs_path=args.logs))


if __name__ == "__main__":
    raise SystemExit(main())
