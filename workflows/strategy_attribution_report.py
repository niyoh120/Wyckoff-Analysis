"""Strategy attribution report workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.constants import TABLE_STRATEGY_ATTRIBUTION_REPORTS
from integrations.supabase_base import (
    close_client,
    create_admin_client,
    create_read_client,
    require_server_write_context,
)
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
        report["created_at"] = datetime.now(UTC).isoformat()
        if not request.no_write:
            write_report(client, report)
        if request.output_dir:
            write_artifacts(report, request.output_dir)
        return report
    finally:
        close_client(client)


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
        "## 降权建议",
    ]
    lines.extend(f"- `{r['target']}` h={r['horizon']}: {r['reason']}" for r in report["recommendations_json"])
    return "\n".join(lines)


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
