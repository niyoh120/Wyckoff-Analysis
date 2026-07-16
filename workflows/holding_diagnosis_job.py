"""Holding diagnosis job workflow: daily-bar rules + LLM report + Telegram delivery."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.wyckoff_engine import FunnelConfig
from utils.telegram import send_to_telegram
from workflows.holding_diagnosis_core import (
    HoldingPortfolioContext,
    build_holding_advices,
    build_holdings_markdown,
    default_holding_portfolio_id,
    fetch_holding_benchmark,
    fetch_holding_daily_frames,
    holding_no_position_meta,
    holding_portfolio_meta,
    resolve_holding_portfolio_context,
)
from workflows.holding_diagnosis_llm import run_holding_llm_report

TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class HoldingDiagnosisRuntime:
    tg_bot_token: str
    tg_chat_id: str
    portfolio_id: str


def runtime_from_env() -> HoldingDiagnosisRuntime:
    return HoldingDiagnosisRuntime(
        tg_bot_token=os.getenv("TG_BOT_TOKEN", "").strip(),
        tg_chat_id=os.getenv("TG_CHAT_ID", "").strip(),
        portfolio_id=default_holding_portfolio_id(),
    )


def run_holding_diagnosis_job(runtime: HoldingDiagnosisRuntime | None = None) -> int:
    started_at = time.time()
    runtime = runtime or runtime_from_env()
    deadline_at = datetime.now(TZ) + timedelta(minutes=10)
    print(f"[holding-diag] portfolio={runtime.portfolio_id}")

    context = resolve_holding_portfolio_context(runtime.portfolio_id)
    if not context.positions:
        print(f"[holding-diag] no holdings to diagnose: {holding_no_position_meta(context)}")
        return 0

    report = _build_holding_diagnosis_report(
        context=context, portfolio_id=runtime.portfolio_id, deadline_at=deadline_at, started_at=started_at
    )
    print(report)
    _send_holding_report(report, runtime)
    return 0


def _build_holding_diagnosis_report(
    *,
    context: HoldingPortfolioContext,
    portfolio_id: str,
    deadline_at: datetime,
    started_at: float,
) -> str:
    df_map = fetch_holding_daily_frames(context.positions)
    bench_df = fetch_holding_benchmark()
    holdings = build_holding_advices(context.positions, df_map, bench_df, FunnelConfig())
    rule_section = build_holdings_markdown(holdings=holdings, portfolio_meta=holding_portfolio_meta(context))
    return run_holding_llm_report(
        holdings=holdings,
        rule_section=rule_section,
        portfolio_id=portfolio_id,
        deadline_at=deadline_at,
        started_at=started_at,
        log=print,
    )


def _send_holding_report(report: str, runtime: HoldingDiagnosisRuntime) -> bool:
    if runtime.tg_bot_token and runtime.tg_chat_id:
        ok = send_to_telegram(
            f"📊 持仓诊断\n\n{report}",
            tg_bot_token=runtime.tg_bot_token,
            tg_chat_id=runtime.tg_chat_id,
        )
        print(f"[holding-diag] Telegram: {'ok' if ok else 'failed'}")
        return bool(ok)
    print("[holding-diag] Telegram not configured, skipping push")
    return False
