"""CLI entrypoint for safe recommendation_tracking backfill."""

from __future__ import annotations

import argparse
from datetime import date, datetime

import _bootstrap  # noqa: F401

from integrations.fetch_a_share_csv import cached_trade_dates
from workflows.recommendation_backfill import RecommendationBackfillRequest, run_recommendation_backfill


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全回刷 recommendation_tracking 指定交易日数据")
    parser.add_argument("--dates", default="", help="逗号分隔 YYYY-MM-DD；为空时使用最近 N 个交易日")
    parser.add_argument("--latest", type=int, default=5, help="--dates 为空时回刷最近 N 个交易日")
    parser.add_argument("--anchor", default=date.today().isoformat(), help="最近交易日锚点，YYYY-MM-DD")
    parser.add_argument("--output-dir", default="artifacts/recommendation_backfill", help="artifact 输出目录")
    parser.add_argument("--apply", action="store_true", help="确认写库替换；默认只生成 artifact")
    parser.add_argument("--skip-step3", action="store_true", help="跳过 Step3 AI 标记")
    parser.add_argument("--allow-empty-date", action="store_true", help="允许某个目标日期新结果为空并删除旧行")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_recommendation_backfill(
        RecommendationBackfillRequest(
            dates=tuple(_resolve_dates(args.dates, args.latest, args.anchor)),
            output_dir=args.output_dir,
            apply=bool(args.apply),
            skip_step3=bool(args.skip_step3),
            allow_empty_date=bool(args.allow_empty_date),
        )
    )


def _resolve_dates(raw_dates: str, latest: int, anchor: str) -> list[date]:
    dates = [_parse_date(item) for item in raw_dates.split(",") if item.strip()]
    if dates:
        return dates
    anchor_date = _parse_date(anchor)
    trading_days = [day for day in cached_trade_dates() if day <= anchor_date]
    return list(trading_days[-max(int(latest), 1) :])


def _parse_date(raw: str) -> date:
    return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()


if __name__ == "__main__":
    raise SystemExit(main())
