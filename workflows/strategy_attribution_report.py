"""Strategy attribution report workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.constants import TABLE_STRATEGY_ATTRIBUTION_REPORTS
from core.strategy_policy_display import format_policy_signal_label
from integrations.supabase_base import (
    close_client,
    create_admin_client,
    create_read_client,
    require_server_write_context,
)
from workflows.strategy_attribution_execution import attribution_execution_state
from workflows.strategy_attribution_stats import build_strategy_attribution_payload


@dataclass(frozen=True)
class StrategyAttributionRequest:
    market: str = "cn"
    days: int = 30
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20)
    output_dir: Path | None = None
    no_write: bool = False


def parse_horizons(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in str(raw or "").split(",") if x.strip())


def run_strategy_attribution_report(request: StrategyAttributionRequest) -> dict[str, Any]:
    client = create_report_client(no_write=request.no_write)
    try:
        report = build_report(client, request.market, request.days, list(request.horizons))
        attach_policy_execution_state(report)
        report["created_at"] = datetime.now(UTC).isoformat()
        if not request.no_write:
            write_report(client, report)
        if request.output_dir:
            write_artifacts(report, request.output_dir)
        return report
    finally:
        close_client(client)


def build_console_summary(report: dict[str, Any], *, written: bool) -> dict[str, Any]:
    governor = _report_policy_governor(report)
    shadow = report.get("shadow_diff_stats_json") or {}
    execution = _report_policy_execution_state(report)
    return {
        "market": report.get("market"),
        "report_date": report.get("report_date"),
        "written": written,
        "policy_status": governor.get("status", "unknown"),
        "mode_recommendation": governor.get("mode_recommendation", "keep_shadow"),
        "auto_apply": bool(governor.get("auto_apply")),
        "policy_summary": governor.get("summary", "-"),
        "shadow_runs": shadow.get("count", 0) if isinstance(shadow, dict) else 0,
        "execution_policy": execution.get("funnel_dynamic_policy", "off"),
        "execution_horizon": execution.get("horizon", "5"),
        "execution_scope": execution.get("scope", "none"),
        "signal_action_count": execution.get("signal_action_count", 0),
    }


def build_report(client: Any, market: str, days: int, horizons: list[int]) -> dict[str, Any]:
    end = date.today()
    start = end - timedelta(days=days)
    observations = fetch_all(client, "signal_observations", "*", market=market, start=start, end=end)
    outcomes = fetch_all(client, "signal_outcomes", "*", market=market, start=start, end=end)
    shadow = fetch_all(client, "signal_policy_shadow_runs", "*", market=market, start=start, end=end)
    return build_strategy_attribution_payload(
        report_date=end,
        market=market,
        window_start=start,
        window_end=end,
        horizons=horizons,
        observations=observations,
        outcomes=outcomes,
        shadow_runs=shadow,
    )


def fetch_all(client: Any, table: str, select: str, *, market: str, start: date, end: date) -> list[dict[str, Any]]:
    date_col = "trade_date" if table != "strategy_attribution_reports" else "report_date"
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch = _fetch_page(
            client, table, select, market=market, start=start, end=end, date_col=date_col, offset=offset
        )
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += 1000


def write_report(client: Any, report: dict[str, Any]) -> None:
    client.table(TABLE_STRATEGY_ATTRIBUTION_REPORTS).upsert(
        report,
        on_conflict="report_date,market,window_start,window_end",
    ).execute()


def write_artifacts(report: dict[str, Any], output_dir: Path) -> None:
    out = output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(build_report_markdown(report) + "\n", encoding="utf-8")


def build_report_markdown(report: dict[str, Any]) -> str:
    shadow = report.get("shadow_diff_stats_json") or {}
    shadow_h5 = ((shadow.get("outcome_stats") or {}).get("5") or {}) if isinstance(shadow, dict) else {}
    governor = _report_policy_governor(report)
    execution = _report_policy_execution_state(report)
    lines = [
        f"# 策略归因报告 {report['report_date']}",
        "",
        f"- 市场: `{report['market']}`",
        f"- 窗口: `{report['window_start']}` 至 `{report['window_end']}`",
        "",
        "## Shadow 差异",
        f"- run 数: `{shadow.get('count', 0) if isinstance(shadow, dict) else 0}`",
        f"- 平均新增: `{shadow.get('avg_added', 0) if isinstance(shadow, dict) else 0}`",
        f"- 平均移除: `{shadow.get('avg_removed', 0) if isinstance(shadow, dict) else 0}`",
        f"- h=5 新增组: `{json.dumps(shadow_h5.get('added') or {}, ensure_ascii=False)}`",
        f"- h=5 移除组: `{json.dumps(shadow_h5.get('removed') or {}, ensure_ascii=False)}`",
        "",
        "## 运营复盘",
        *_operations_markdown_lines(report),
        "",
        "## 策略治理",
        f"- 状态: `{governor.get('status', 'unknown') if isinstance(governor, dict) else 'unknown'}`",
        f"- 动态策略建议: `{governor.get('mode_recommendation', 'keep_shadow') if isinstance(governor, dict) else 'keep_shadow'}`",
        f"- 自动生效: `{bool(governor.get('auto_apply')) if isinstance(governor, dict) else False}`",
        f"- 摘要: {governor.get('summary', '-') if isinstance(governor, dict) else '-'}",
        "",
        "## 调权执行状态",
        f"- 漏斗动态策略: `{execution.get('funnel_dynamic_policy', 'off')}`",
        f"- 执行周期: `h={execution.get('horizon', '5')}`",
        f"- 当前作用范围: `{execution.get('scope', 'none')}`",
        f"- 可执行调权: `{execution.get('signal_action_count', 0)}`",
        f"- 摘要: {execution.get('summary', '暂无可执行信号调权。')}",
        "",
        "## 信号权重建议",
    ]
    lines.extend(_recommendation_markdown_rows(report.get("recommendations_json") or []))
    return "\n".join(lines)


def _operations_markdown_lines(report: dict[str, Any]) -> list[str]:
    shadow = report.get("shadow_diff_stats_json") or {}
    latest = shadow.get("latest") if isinstance(shadow, dict) else {}
    execution = _report_policy_execution_state(report)
    lines = _latest_shadow_lines(latest if isinstance(latest, dict) else {})
    lines.extend(_action_detail_lines(execution.get("action_details") if isinstance(execution, dict) else []))
    return lines or ["- 暂无可用运营复盘信息。"]


def _latest_shadow_lines(latest: dict[str, Any]) -> list[str]:
    if not latest:
        return ["- 最新 shadow: 暂无。"]
    selection = latest.get("selection_summary") if isinstance(latest.get("selection_summary"), dict) else {}
    added_sample = ", ".join(str(x) for x in latest.get("diff_added_sample") or []) or "-"
    removed_sample = ", ".join(str(x) for x in latest.get("diff_removed_sample") or []) or "-"
    return [
        (
            f"- 最新 shadow: `{latest.get('trade_date', '-')}` / `{latest.get('regime', '-')}`，"
            f"base `{selection.get('base_count', '-')}` -> shadow `{selection.get('shadow_count', '-')}`，"
            f"新增 `{selection.get('diff_added_count', '-')}`，移除 `{selection.get('diff_removed_count', '-')}`，"
            f"Jaccard `{selection.get('jaccard', '-')}`"
        ),
        f"- Shadow 新增样本: `{added_sample}`",
        f"- Shadow 移除样本: `{removed_sample}`",
    ]


def _action_detail_lines(raw: Any) -> list[str]:
    rows = raw if isinstance(raw, list) else []
    if not rows:
        return ["- 本期可执行调权: 无。"]
    lines = ["- 本期可执行调权:"]
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        lines.append(
            f"  - `{row.get('label', row.get('target', '-'))}` {row.get('action', '-')}"
            f" ×{row.get('weight_multiplier', 1.0)}；"
            f"avg={evidence.get('avg_return_pct', '-')}，win={evidence.get('win_rate_pct', '-')}%，"
            f"dd={evidence.get('avg_drawdown_pct', '-')}"
        )
    if len(rows) > 8:
        lines.append(f"  - ... 另 {len(rows) - 8} 项")
    return lines


def _report_policy_governor(report: dict[str, Any]) -> dict[str, Any]:
    shadow = report.get("shadow_diff_stats_json") or {}
    if not isinstance(shadow, dict):
        return {}
    governor = shadow.get("policy_governor")
    return governor if isinstance(governor, dict) else {}


def attach_policy_execution_state(report: dict[str, Any]) -> None:
    shadow = report.get("shadow_diff_stats_json")
    if not isinstance(shadow, dict):
        return
    shadow["policy_execution_state"] = attribution_execution_state(
        _report_policy_governor(report),
        list(report.get("recommendations_json") or []),
    )


def _report_policy_execution_state(report: dict[str, Any]) -> dict[str, Any]:
    shadow = report.get("shadow_diff_stats_json") or {}
    if isinstance(shadow, dict) and isinstance(shadow.get("policy_execution_state"), dict):
        return shadow["policy_execution_state"]
    return attribution_execution_state(_report_policy_governor(report), list(report.get("recommendations_json") or []))


def _recommendation_markdown_rows(rows: list[dict[str, Any]]) -> list[str]:
    rendered = []
    for row in rows:
        if row.get("type") == "policy_governor":
            continue
        payload = _json_payload(row.get("reason"))
        action = str(row.get("type") or payload.get("action") or "watch")
        weight = payload.get("weight_multiplier", "-")
        evidence = payload.get("evidence") or {}
        target = format_policy_signal_label(row.get("target") or payload.get("target"), payload.get("scope") or {})
        rendered.append(
            f"- `{target}` h={row.get('horizon')}: {action}, weight={weight}, "
            f"avg={evidence.get('avg_return_pct', '-')}, win={evidence.get('win_rate_pct', '-')}%, "
            f"dd={evidence.get('avg_drawdown_pct', '-')}"
        )
    return rendered or ["- 暂无需要调整的信号。"]


def _json_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def create_report_client(*, no_write: bool) -> Any:
    if no_write:
        return create_user_read_client() or create_read_client()
    require_server_write_context("write strategy_attribution_reports")
    return create_admin_client()


def create_user_read_client() -> Any | None:
    try:
        from integrations.local_auth import restore_session
        from integrations.supabase_base import create_user_client

        session = restore_session()
        if session and session.get("access_token"):
            return create_user_client(session["access_token"], session.get("refresh_token", ""))
    except Exception:
        return None
    return None


def _fetch_page(
    client: Any,
    table: str,
    select: str,
    *,
    market: str,
    start: date,
    end: date,
    date_col: str,
    offset: int,
) -> list[dict[str, Any]]:
    query = (
        client.table(table)
        .select(select)
        .eq("market", market)
        .gte(date_col, start.isoformat())
        .lte(date_col, end.isoformat())
        .range(offset, offset + 999)
    )
    return query.execute().data or []
