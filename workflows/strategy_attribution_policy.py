"""Read-only strategy attribution policy inputs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.constants import TABLE_STRATEGY_ATTRIBUTION_REPORTS
from core.strategy_policy_governor import signal_weight_multipliers_from_rows
from integrations.supabase_base import close_client, create_read_client

LOCAL_ATTRIBUTION_REPORT = Path("/private/tmp/wyckoff-strategy-attribution/latest/report.json")


def load_attribution_signal_weights(
    *,
    market: str = "cn",
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, float]:
    try:
        row = load_latest_attribution_report(market)
    except Exception as exc:
        _log(log_fn, f"策略归因调权读取失败，跳过: {exc}")
        row = None
    row = row or load_local_attribution_report(market)
    if not row:
        _log(log_fn, "策略归因调权: 暂无归因报告，跳过。")
        return {}
    weights = signal_weight_multipliers_from_rows(row.get("recommendations_json"), horizon=policy_horizon(row))
    if weights:
        _log(log_fn, "策略归因调权: " + ", ".join(f"{k}=x{v:.2f}" for k, v in weights.items()))
    else:
        _log(log_fn, "策略归因调权: 最新报告无可执行信号权重。")
    return weights


def load_latest_attribution_report(market: str) -> dict[str, Any] | None:
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


def load_local_attribution_report(market: str) -> dict[str, Any] | None:
    path = Path(
        os.getenv("STRATEGY_ATTRIBUTION_REPORT_JSON")
        or os.getenv("TAIL_BUY_ATTRIBUTION_REPORT_JSON")
        or LOCAL_ATTRIBUTION_REPORT
    )
    if not path.exists():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(row, dict) or str(row.get("market") or market) != market:
        return None
    return row


def policy_horizon(row: dict[str, Any]) -> str:
    shadow = row.get("shadow_diff_stats_json")
    if isinstance(shadow, dict):
        governor = shadow.get("policy_governor")
        if isinstance(governor, dict) and governor.get("horizon"):
            return str(governor["horizon"])
    return "5"


def _log(log_fn: Callable[[str], None] | None, message: str) -> None:
    if log_fn:
        log_fn(message)
