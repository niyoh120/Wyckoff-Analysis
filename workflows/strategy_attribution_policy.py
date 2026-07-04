"""Read-only strategy attribution policy inputs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from core.constants import TABLE_STRATEGY_ATTRIBUTION_REPORTS
from core.strategy_policy_display import format_policy_weight_text
from core.strategy_policy_governor import signal_weight_multipliers_from_rows
from integrations.supabase_base import close_client, create_read_client
from workflows.strategy_attribution_execution import attribution_execution_state

LOCAL_ATTRIBUTION_REPORT = Path("/private/tmp/wyckoff-strategy-attribution/latest/report.json")


@dataclass(frozen=True)
class AttributionPolicySnapshot:
    weights: dict[str, float] = field(default_factory=dict)
    source: str = ""
    report_date: str = ""
    horizon: str = "5"
    age_days: int | None = None
    max_age_days: int = 7
    governor_status: str = ""
    mode_recommendation: str = ""
    next_action: str = ""
    next_action_summary: str = ""
    auto_apply: bool = False
    execution_policy: str = ""
    execution_scope: str = ""
    signal_action_count: int = 0
    execution_summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "report_date": self.report_date,
            "horizon": self.horizon,
            "age_days": self.age_days,
            "max_age_days": self.max_age_days,
            "weight_count": len(self.weights),
            "governor_status": self.governor_status,
            "mode_recommendation": self.mode_recommendation,
            "next_action": self.next_action,
            "next_action_summary": self.next_action_summary,
            "auto_apply": self.auto_apply,
            "execution_policy": self.execution_policy,
            "execution_scope": self.execution_scope,
            "signal_action_count": self.signal_action_count,
            "execution_summary": self.execution_summary,
        }


def load_attribution_signal_weights(
    *,
    market: str = "cn",
    log_fn: Callable[[str], None] | None = None,
    as_of: date | None = None,
) -> dict[str, float]:
    return load_attribution_policy_snapshot(market=market, log_fn=log_fn, as_of=as_of).weights


def load_attribution_policy_snapshot(
    *,
    market: str = "cn",
    log_fn: Callable[[str], None] | None = None,
    as_of: date | None = None,
) -> AttributionPolicySnapshot:
    today = as_of or date.today()
    max_age = _max_report_age_days()
    try:
        row = load_latest_attribution_report(market)
    except Exception as exc:
        _log(log_fn, f"策略归因调权读取失败，跳过: {exc}")
        row = None
    row, source = _select_fresh_report(row, market=market, today=today, log_fn=log_fn)
    if not row:
        _log(log_fn, "策略归因调权: 暂无归因报告，跳过。")
        return AttributionPolicySnapshot(max_age_days=max_age)
    horizon = policy_horizon(row)
    weights = signal_weight_multipliers_from_rows(row.get("recommendations_json"), horizon=horizon)
    snapshot = _policy_snapshot(row, weights, source=source, today=today, max_age=max_age, horizon=horizon)
    if weights:
        _log(log_fn, "策略归因调权: " + _snapshot_log_text(snapshot))
    else:
        _log(log_fn, "策略归因调权: 最新报告无可执行信号权重。")
    return snapshot


def load_latest_attribution_report(market: str) -> dict[str, Any] | None:
    client = create_read_client()
    try:
        rows = (
            client.table(TABLE_STRATEGY_ATTRIBUTION_REPORTS)
            .select("report_date,created_at,market,shadow_diff_stats_json,recommendations_json")
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


def _select_fresh_report(
    remote_row: dict[str, Any] | None,
    *,
    market: str,
    today: date,
    log_fn: Callable[[str], None] | None,
) -> tuple[dict[str, Any] | None, str]:
    remote = _fresh_report(remote_row, today=today, log_fn=log_fn, source="远端")
    local = _fresh_report(load_local_attribution_report(market), today=today, log_fn=log_fn, source="本地")
    if _has_explicit_local_report_path():
        return _newest_report_source(remote, local)
    if remote:
        return remote, "远端"
    return (local, "本地") if local else (None, "")


def _has_explicit_local_report_path() -> bool:
    return bool(os.getenv("STRATEGY_ATTRIBUTION_REPORT_JSON") or os.getenv("TAIL_BUY_ATTRIBUTION_REPORT_JSON"))


def _newest_report_source(
    remote: dict[str, Any] | None,
    local: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    candidates = [(remote, "远端"), (local, "本地")]
    candidates = [(row, source) for row, source in candidates if row]
    if not candidates:
        return None, ""
    return max(candidates, key=lambda item: (_report_day(item[0]) or date.min, 1 if item[1] == "远端" else 0))


def _policy_snapshot(
    row: dict[str, Any],
    weights: dict[str, float],
    *,
    source: str,
    today: date,
    max_age: int,
    horizon: str,
) -> AttributionPolicySnapshot:
    report_day = _report_day(row)
    governor = _policy_governor(row)
    execution = attribution_execution_state(governor, _recommendation_rows(row.get("recommendations_json")))
    return AttributionPolicySnapshot(
        weights=weights,
        source=source,
        report_date=report_day.isoformat() if report_day else "",
        horizon=str(horizon or "5"),
        age_days=(today - report_day).days if report_day else None,
        max_age_days=max_age,
        governor_status=str(governor.get("status") or ""),
        mode_recommendation=str(governor.get("mode_recommendation") or ""),
        next_action=str(governor.get("next_action") or ""),
        next_action_summary=str(governor.get("next_action_summary") or ""),
        auto_apply=bool(governor.get("auto_apply")),
        execution_policy=str(execution.get("funnel_dynamic_policy") or ""),
        execution_scope=str(execution.get("scope") or ""),
        signal_action_count=int(execution.get("signal_action_count") or 0),
        execution_summary=str(execution.get("summary") or ""),
    )


def _snapshot_log_text(snapshot: AttributionPolicySnapshot) -> str:
    meta = []
    if snapshot.source:
        meta.append(snapshot.source)
    if snapshot.report_date:
        meta.append(f"report_date={snapshot.report_date}")
    meta.append(f"h={snapshot.horizon}")
    if snapshot.age_days is not None:
        meta.append(f"age={snapshot.age_days}d")
    if snapshot.execution_policy:
        meta.append(f"mode={snapshot.execution_policy}")
    if snapshot.execution_scope:
        meta.append(f"scope={snapshot.execution_scope}")
    if snapshot.next_action:
        meta.append(f"next={snapshot.next_action}")
    weights = format_policy_weight_text(snapshot.weights, limit=12, delimiter=", ")
    return f"{' '.join(meta)}; {weights}"


def _policy_governor(row: dict[str, Any]) -> dict[str, Any]:
    shadow = row.get("shadow_diff_stats_json")
    if not isinstance(shadow, dict):
        return {}
    governor = shadow.get("policy_governor")
    return governor if isinstance(governor, dict) else {}


def _recommendation_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _fresh_report(
    row: dict[str, Any] | None,
    *,
    today: date,
    log_fn: Callable[[str], None] | None,
    source: str,
) -> dict[str, Any] | None:
    if not row:
        return None
    max_age = _max_report_age_days()
    if max_age <= 0:
        return row
    report_day = _report_day(row)
    if report_day is None:
        _log(log_fn, f"策略归因调权: {source}报告缺少 report_date，跳过。")
        return None
    age = (today - report_day).days
    if age < 0 or age > max_age:
        _log(log_fn, f"策略归因调权: {source}报告已过期(report_date={report_day}, age={age}d)，跳过。")
        return None
    return row


def _report_day(row: dict[str, Any]) -> date | None:
    raw = row.get("report_date") or row.get("created_at")
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _max_report_age_days() -> int:
    raw = os.getenv("STRATEGY_ATTRIBUTION_MAX_AGE_DAYS", "7")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 7


def _log(log_fn: Callable[[str], None] | None, message: str) -> None:
    if log_fn:
        log_fn(message)
