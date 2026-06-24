"""US recommendation performance refresh job orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from integrations.recommendation_performance import refresh_us_tracking_performance

TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class UsRecommendationPerformanceRequest:
    logs_path: str = ""
    max_dates: int = 60
    kline_count: int = 160


def run_us_recommendation_performance_job(request: UsRecommendationPerformanceRequest) -> int:
    logs_path = str(request.logs_path or "").strip() or None
    _log(
        f"开始执行美股推荐表现回刷 max_dates={request.max_dates}, kline_count={request.kline_count}",
        logs_path,
    )
    try:
        summary = refresh_us_tracking_performance(
            max_dates=request.max_dates,
            kline_count=request.kline_count,
        )
    except Exception as exc:
        _log(f"任务失败: {exc}", logs_path)
        return 1
    _log(_summary_line(summary), logs_path)
    return 0


def _summary_line(summary: dict) -> str:
    return (
        "任务完成: "
        f"rows_total={summary.get('rows_total', 0)}, "
        f"rows_updated={summary.get('rows_updated', 0)}, "
        f"rows_skipped={summary.get('rows_skipped', 0)}, "
        f"codes_total={summary.get('codes_total', 0)}, "
        f"codes_no_data={summary.get('codes_no_data', 0)}, "
        f"latest_trade_date={summary.get('latest_trade_date', '') or '-'}, "
        f"mfe_ge_5={summary.get('mfe_ge_5', 0)}, "
        f"mfe_ge_10={summary.get('mfe_ge_10', 0)}, "
        f"mae_le_neg5={summary.get('mae_le_neg5', 0)}"
    )


def _log(msg: str, logs_path: str | None = None) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    if logs_path:
        os.makedirs(os.path.dirname(logs_path) or ".", exist_ok=True)
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
