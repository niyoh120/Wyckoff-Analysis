"""Strategy attribution report workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.constants import TABLE_STRATEGY_ATTRIBUTION_REPORTS
from core.strategy_policy_display import (
    format_policy_signal_label,
    policy_execution_display,
    policy_governor_display,
    policy_mode_recommendation_label,
    policy_next_action_label,
    policy_promotion_status_label,
)
from integrations.supabase_base import (
    close_client,
    create_admin_client,
    create_read_client,
    require_server_write_context,
)
from workflows.strategy_attribution_execution import attribution_execution_state, attribution_operations_brief
from workflows.strategy_attribution_stats import build_strategy_attribution_payload


@dataclass(frozen=True)
class StrategyAttributionRequest:
    market: str = "cn"
    days: int = 30
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20)
    output_dir: Path | None = None
    no_write: bool = False
    backtest_confirmation_json: dict[str, Any] | None = None


def parse_horizons(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in str(raw or "").split(",") if x.strip())


def run_strategy_attribution_report(request: StrategyAttributionRequest) -> dict[str, Any]:
    client = create_report_client(no_write=request.no_write)
    try:
        report = build_report(
            client,
            request.market,
            request.days,
            list(request.horizons),
            backtest_confirmation_json=request.backtest_confirmation_json,
        )
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
        "next_action": governor.get("next_action", "keep_shadow_observe"),
        "next_action_summary": governor.get("next_action_summary", "-"),
        "promotion_status": governor.get("promotion_status", "unknown"),
        "auto_apply": bool(governor.get("auto_apply")),
        "policy_summary": governor.get("summary", "-"),
        "policy_display": policy_governor_display(governor),
        "shadow_runs": shadow.get("count", 0) if isinstance(shadow, dict) else 0,
        "execution_policy": execution.get("funnel_dynamic_policy", "off"),
        "execution_horizon": execution.get("horizon", "5"),
        "execution_scope": execution.get("scope", "none"),
        "execution_summary": policy_execution_display(execution),
        "formal_dynamic_allowed": bool(execution.get("formal_dynamic_allowed")),
        "formal_dynamic_block_reason": execution.get("formal_dynamic_block_reason", ""),
        "active_scope": execution.get("active_scope", "无"),
        "tail_buy_weights_active": bool(execution.get("tail_buy_weights_active")),
        "funnel_shadow_weights_active": bool(execution.get("funnel_shadow_weights_active")),
        "funnel_formal_weights_active": bool(execution.get("funnel_formal_weights_active")),
        "signal_action_count": execution.get("signal_action_count", 0),
        "operator_summary": _report_policy_operations(report).get("operator_summary", "-"),
    }


def build_report(
    client: Any,
    market: str,
    days: int,
    horizons: list[int],
    *,
    backtest_confirmation_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        backtest_confirmation_json=backtest_confirmation_json,
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
        f"- 状态: {_governor_status_text(governor)}",
        f"- 动态策略建议: {_mode_recommendation_text(governor)}",
        f"- 下一步动作: {_next_action_text(governor)}",
        f"- 下一步说明: {governor.get('next_action_summary', '-') if isinstance(governor, dict) else '-'}",
        f"- 晋级状态: {_promotion_status_text(governor)}",
        f"- 自动生效: `{bool(governor.get('auto_apply')) if isinstance(governor, dict) else False}`",
        f"- 摘要: {governor.get('summary', '-') if isinstance(governor, dict) else '-'}",
        "",
        "### 晋级检查",
        *_promotion_checklist_lines(governor),
        "",
        "## 调权执行状态",
        f"- 漏斗动态策略: `{execution.get('funnel_dynamic_policy', 'off')}`",
        f"- 执行周期: `h={execution.get('horizon', '5')}`",
        f"- 当前生效范围: `{execution.get('active_scope', '无')}`",
        f"- 底层 scope: `{execution.get('scope', 'none')}`",
        f"- 可执行调权: `{execution.get('signal_action_count', 0)}`",
        f"- 摘要: {execution.get('summary', '暂无可执行信号调权。')}",
        "",
        "## 信号权重建议",
    ]
    lines.extend(_recommendation_markdown_rows(report.get("recommendations_json") or []))
    return "\n".join(lines)


def _governor_status_text(governor: dict[str, Any]) -> str:
    raw = _governor_value(governor, "status", "unknown")
    return _label_with_raw(policy_governor_display(governor).get("status", "未知"), raw)


def _mode_recommendation_text(governor: dict[str, Any]) -> str:
    raw = _governor_value(governor, "mode_recommendation", "keep_shadow")
    return _label_with_raw(policy_mode_recommendation_label(raw), raw)


def _next_action_text(governor: dict[str, Any]) -> str:
    raw = _governor_value(governor, "next_action", "keep_shadow_observe")
    return _label_with_raw(policy_next_action_label(raw), raw)


def _promotion_status_text(governor: dict[str, Any]) -> str:
    raw = _governor_value(governor, "promotion_status", "unknown")
    return _label_with_raw(policy_promotion_status_label(raw), raw)


def _governor_value(governor: dict[str, Any], key: str, default: str) -> str:
    if not isinstance(governor, dict):
        return default
    return str(governor.get(key) or default).strip()


def _label_with_raw(label: str, raw: str) -> str:
    return f"{label} (`{raw}`)"


def _operations_markdown_lines(report: dict[str, Any]) -> list[str]:
    shadow = report.get("shadow_diff_stats_json") or {}
    latest = shadow.get("latest") if isinstance(shadow, dict) else {}
    execution = _report_policy_execution_state(report)
    operations = _report_policy_operations(report)
    lines = [f"- 操作摘要: {operations.get('operator_summary', '-')}"]
    lines.extend(_latest_shadow_lines(latest if isinstance(latest, dict) else {}))
    lines.extend(_action_detail_lines(execution.get("action_details") if isinstance(execution, dict) else []))
    return lines or ["- 暂无可用运营复盘信息。"]


def _promotion_checklist_lines(governor: dict[str, Any]) -> list[str]:
    rows = governor.get("promotion_checklist") if isinstance(governor, dict) else []
    if not isinstance(rows, list) or not rows:
        return ["- 暂无晋级检查清单。"]
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(f"- `{row.get('key', '-')}`: `{row.get('status', '-')}` — {row.get('summary', '-')}")
    return lines or ["- 暂无晋级检查清单。"]


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
    execution = attribution_execution_state(
        _report_policy_governor(report), list(report.get("recommendations_json") or [])
    )
    shadow["policy_execution_state"] = execution
    shadow["policy_operations_brief"] = attribution_operations_brief(shadow, execution)


def _report_policy_execution_state(report: dict[str, Any]) -> dict[str, Any]:
    shadow = report.get("shadow_diff_stats_json") or {}
    if isinstance(shadow, dict) and isinstance(shadow.get("policy_execution_state"), dict):
        return shadow["policy_execution_state"]
    return attribution_execution_state(_report_policy_governor(report), list(report.get("recommendations_json") or []))


def _report_policy_operations(report: dict[str, Any]) -> dict[str, Any]:
    shadow = report.get("shadow_diff_stats_json") or {}
    if isinstance(shadow, dict) and isinstance(shadow.get("policy_operations_brief"), dict):
        return shadow["policy_operations_brief"]
    return attribution_operations_brief(
        shadow if isinstance(shadow, dict) else {}, _report_policy_execution_state(report)
    )


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
