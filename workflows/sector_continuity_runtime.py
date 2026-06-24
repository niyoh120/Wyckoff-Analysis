"""Runtime workflow for sector-continuity report jobs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from integrations.market_metadata import CONCEPT_HEAT_HISTORY, fetch_concept_heat
from integrations.supabase_concept_heat import load_concept_heat_history_from_supabase, upsert_concept_heat_history
from utils.feishu import send_feishu_notification
from utils.trading_clock import is_a_share_trading_day, resolve_end_calendar_day
from workflows.sector_continuity_report import build_sector_continuity_report, update_history_with_trade_date


@dataclass(frozen=True)
class SectorContinuityResult:
    report: str
    report_path: Path
    history_days: int
    messages: tuple[str, ...]


@dataclass(frozen=True)
class SectorContinuityNotification:
    attempted: bool
    ok: bool
    title: str
    reason: str


def resolve_sector_trade_date() -> date | None:
    trade_date = resolve_end_calendar_day()
    return trade_date if is_a_share_trading_day(trade_date) else None


def build_sector_continuity_result(
    trade_date: date,
    *,
    output_dir: Path = Path("logs"),
) -> SectorContinuityResult | None:
    messages = ["[sector_continuity] 加载概念热度..."]
    heat = fetch_concept_heat()
    history = _load_history(messages)
    history = _merge_today_heat(history, heat, trade_date, messages)
    if not history:
        return None

    report = build_sector_continuity_report(history)
    output_dir.mkdir(exist_ok=True)
    report_path = output_dir / "sector_continuity_report.md"
    report_path.write_text(report, encoding="utf-8")
    messages.append(f"[sector_continuity] 历史覆盖 {len(history)} 个交易日")
    messages.append(f"[sector_continuity] 报告已生成: {report_path}")
    return SectorContinuityResult(report, report_path, len(history), tuple(messages))


def notify_sector_continuity_report(
    report: str,
    trade_date: date,
    *,
    webhook: str | None = None,
) -> SectorContinuityNotification:
    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip() if webhook is None else webhook.strip()
    title = f"板块延续性报告 {trade_date.isoformat()}"
    if not webhook:
        return SectorContinuityNotification(False, False, title, "FEISHU_WEBHOOK_URL 未配置")
    ok = bool(send_feishu_notification(webhook, title, report))
    return SectorContinuityNotification(True, ok, title, "ok" if ok else "failed")


def _load_history(messages: list[str]) -> dict:
    history = load_concept_heat_history_from_supabase()
    if history:
        messages.append(f"[sector_continuity] Supabase 历史覆盖 {len(history)} 个交易日")
        return history
    if not CONCEPT_HEAT_HISTORY.exists():
        return {}
    with open(CONCEPT_HEAT_HISTORY, encoding="utf-8") as f:
        return json.load(f)


def _merge_today_heat(history: dict, heat: list[dict], trade_date: date, messages: list[str]) -> dict:
    if not heat:
        return history
    written = upsert_concept_heat_history(trade_date.isoformat(), heat)
    if written:
        messages.append(f"[sector_continuity] Supabase 写入 {trade_date.isoformat()} 概念热度 {written} 条")
    return update_history_with_trade_date(history, heat, trade_date)
