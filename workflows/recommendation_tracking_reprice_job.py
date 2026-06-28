"""Recommendation tracking reprice job orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from integrations.recommendation_performance import refresh_tracking_performance
from integrations.supabase_tail_buy import refresh_tail_buy_prices_with_tickflow_realtime
from workflows.recommendation_tracking_reprice import (
    refresh_global_tracking_prices,
    refresh_tracking_prices_with_tickflow_realtime,
)

TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class RecommendationRepriceRequest:
    logs_path: str = ""
    market: str = "cn"


def run_recommendation_reprice_job(request: RecommendationRepriceRequest) -> int:
    logs_path = str(request.logs_path or "").strip() or None
    market = str(request.market or "cn").strip().lower()
    _log(f"开始执行 recommendation tracking 回填任务 market={market}", logs_path)
    try:
        summary = _run_market_reprice(market, logs_path)
    except Exception as e:
        _log(f"任务失败: {e}", logs_path)
        return 1

    _log(_summary_line(summary), logs_path)
    return 0


def _run_market_reprice(market: str, logs_path: str | None) -> dict:
    summary = (
        refresh_global_tracking_prices(market) if market != "cn" else refresh_tracking_prices_with_tickflow_realtime()
    )
    _refresh_tracking_performance(market, logs_path)
    if market == "cn":
        _refresh_tail_buy_prices(logs_path)
    return summary


def _refresh_tracking_performance(market: str, logs_path: str | None) -> None:
    try:
        perf_summary = refresh_tracking_performance(
            market,
            max_dates=_int_env("RECOMMENDATION_PERFORMANCE_MAX_DATES", 60),
            kline_count=_int_env("RECOMMENDATION_PERFORMANCE_KLINE_COUNT", 160),
        )
        _log(_performance_summary_line(perf_summary), logs_path)
    except Exception as perf_exc:
        _log(f"推荐表现刷新失败（价格主任务已完成）: {perf_exc}", logs_path)


def _refresh_tail_buy_prices(logs_path: str | None) -> None:
    try:
        tail_summary = refresh_tail_buy_prices_with_tickflow_realtime()
        _log(
            "尾盘表价格刷新完成: "
            f"rows_total={tail_summary.get('rows_total', 0)}, "
            f"rows_updated={tail_summary.get('rows_updated', 0)}, "
            f"codes_no_data={tail_summary.get('codes_no_data', 0)}, "
            f"schema_missing={tail_summary.get('schema_missing', False)}",
            logs_path,
        )
    except Exception as tail_exc:
        _log(f"尾盘表价格刷新失败（recommendation 主任务已完成）: {tail_exc}", logs_path)


def _summary_line(summary: dict) -> str:
    return (
        "任务完成: "
        f"rows_total={summary.get('rows_total', 0)}, "
        f"rows_updated={summary.get('rows_updated', 0)}, "
        f"rows_skipped={summary.get('rows_skipped', 0)}, "
        f"codes_total={summary.get('codes_total', 0)}, "
        f"codes_no_data={summary.get('codes_no_data', 0)}, "
        f"latest_trade_date={summary.get('latest_trade_date', '') or '-'}"
    )


def _performance_summary_line(summary: dict) -> str:
    return (
        "推荐表现刷新完成: "
        f"rows_total={summary.get('rows_total', 0)}, "
        f"rows_updated={summary.get('rows_updated', 0)}, "
        f"codes_no_data={summary.get('codes_no_data', 0)}, "
        f"latest_trade_date={summary.get('latest_trade_date', '') or '-'}, "
        f"mfe_ge_5={summary.get('mfe_ge_5', 0)}, "
        f"mfe_ge_10={summary.get('mfe_ge_10', 0)}, "
        f"mae_le_neg5={summary.get('mae_le_neg5', 0)}"
    )


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(int(float(raw)), 1)
    except (TypeError, ValueError):
        return default


def _log(msg: str, logs_path: str | None = None) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    if logs_path:
        os.makedirs(os.path.dirname(logs_path) or ".", exist_ok=True)
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
