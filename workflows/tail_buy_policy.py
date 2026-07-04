"""Read-only strategy policy inputs for Tail Buy jobs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.constants import TABLE_STRATEGY_ATTRIBUTION_REPORTS
from core.strategy_policy_governor import signal_weight_multipliers_from_rows
from integrations.supabase_base import close_client, create_read_client
from workflows.tail_buy_utils import log_line

LOCAL_ATTRIBUTION_REPORT = Path("/private/tmp/wyckoff-strategy-attribution/latest/report.json")


def load_tail_buy_policy_adjustments(
    logs_path: str | None = None,
    *,
    market: str = "cn",
) -> dict[str, float]:
    try:
        row = _load_latest_attribution_report(market)
    except Exception as exc:
        log_line(f"策略归因调权读取失败，跳过: {exc}", logs_path)
        row = None
    row = row or _load_local_attribution_report(market)
    if not row:
        log_line("策略归因调权: 暂无归因报告，跳过。", logs_path)
        return {}
    horizon = _policy_horizon(row)
    weights = signal_weight_multipliers_from_rows(row.get("recommendations_json"), horizon=horizon)
    if weights:
        log_line("策略归因调权: " + ", ".join(f"{k}=x{v:.2f}" for k, v in weights.items()), logs_path)
    else:
        log_line("策略归因调权: 最新报告无可执行信号权重。", logs_path)
    return weights


def _load_latest_attribution_report(market: str) -> dict[str, Any] | None:
    client = create_read_client()
    try:
        rows = (
            client.table(TABLE_STRATEGY_ATTRIBUTION_REPORTS)
            .select("report_date,market,shadow_diff_stats_json,recommendations_json")
            .eq("market", market)
            .order("report_date", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None
    finally:
        close_client(client)


def _load_local_attribution_report(market: str) -> dict[str, Any] | None:
    path = Path(os.getenv("TAIL_BUY_ATTRIBUTION_REPORT_JSON") or LOCAL_ATTRIBUTION_REPORT)
    if not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(row, dict) or str(row.get("market") or market) != market:
        return None
    return row


def _policy_horizon(row: dict[str, Any]) -> str:
    shadow = row.get("shadow_diff_stats_json")
    if isinstance(shadow, dict):
        governor = shadow.get("policy_governor")
        if isinstance(governor, dict) and governor.get("horizon"):
            return str(governor["horizon"])
    return "5"
