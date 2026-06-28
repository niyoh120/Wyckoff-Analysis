"""CLI entrypoint for fixed-horizon recommendation event evaluation."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.recommendation_event_eval import (
    RecommendationEventEvalRequest,
    run_recommendation_event_eval,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评估推荐表未来 N 个交易日触及目标涨幅的命中率")
    parser.add_argument("--market", default="cn", choices=["cn", "us", "hk"], help="市场（默认 cn）")
    parser.add_argument("--horizon-days", type=int, default=5, help="未来交易日窗口（默认 5）")
    parser.add_argument("--target-pct", type=float, default=10.0, help="目标最大浮盈百分比（默认 10）")
    parser.add_argument("--max-dates", type=int, default=30, help="仅评估最新 N 个推荐日（默认 30）")
    parser.add_argument("--kline-count", type=int, default=160, help="每只股票拉取日 K 数量（默认 160）")
    parser.add_argument("--output-dir", default="artifacts/recommendation_event_eval", help="artifact 输出目录")
    parser.add_argument("--top-k", default="1,3,5", help="逗号分隔 Top-K 列表（默认 1,3,5）")
    parser.add_argument("--apply-labels", action="store_true", help="将 5 日 +10%% 事件标签写回推荐表")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_recommendation_event_eval(
        RecommendationEventEvalRequest(
            market=args.market,
            horizon_days=args.horizon_days,
            target_pct=args.target_pct,
            max_dates=args.max_dates,
            kline_count=args.kline_count,
            output_dir=args.output_dir,
            top_k=_parse_top_k(args.top_k),
            apply_labels=bool(args.apply_labels),
        )
    )


def _parse_top_k(raw: str) -> tuple[int, ...]:
    values = [int(item.strip()) for item in str(raw or "").split(",") if item.strip()]
    return tuple(values or [1, 3, 5])


if __name__ == "__main__":
    raise SystemExit(main())
