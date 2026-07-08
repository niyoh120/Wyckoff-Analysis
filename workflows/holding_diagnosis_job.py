"""Holding diagnosis job workflow: rules + LLM report + Telegram delivery."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from integrations.tickflow_client import TickFlowClient
from utils.telegram import send_to_telegram
from workflows.holding_diagnosis_llm import run_holding_llm_report
from workflows.tail_buy_config import tail_buy_strategy_config_from_env
from workflows.tail_buy_holdings import analyze_holdings_actions, build_holdings_markdown
from workflows.tail_buy_runtime import holding_stop_config_from_env

TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class HoldingDiagnosisRuntime:
    tickflow_api_key: str
    tg_bot_token: str
    tg_chat_id: str
    portfolio_id: str


def runtime_from_env() -> HoldingDiagnosisRuntime:
    user_id = os.getenv("SUPABASE_USER_ID", "").strip()
    portfolio_id = os.getenv("TAIL_BUY_PORTFOLIO_ID", "").strip() or (
        f"USER_LIVE:{user_id}" if user_id else "USER_LIVE"
    )
    return HoldingDiagnosisRuntime(
        tickflow_api_key=os.getenv("TICKFLOW_API_KEY", "").strip(),
        tg_bot_token=os.getenv("TG_BOT_TOKEN", "").strip(),
        tg_chat_id=os.getenv("TG_CHAT_ID", "").strip(),
        portfolio_id=portfolio_id,
    )


def run_holding_diagnosis_job(runtime: HoldingDiagnosisRuntime | None = None) -> int:
    started_at = time.time()
    runtime = runtime or runtime_from_env()
    if not runtime.tickflow_api_key:
        print("[holding-diag] ERROR: TICKFLOW_API_KEY not set")
        return 1

    deadline_at = datetime.now(TZ) + timedelta(minutes=10)
    print(f"[holding-diag] portfolio={runtime.portfolio_id}")
    holdings, limit_hit, meta = analyze_holdings_actions(
        tickflow_client=TickFlowClient(api_key=runtime.tickflow_api_key),
        portfolio_id=runtime.portfolio_id,
        signal_map={},
        style="conservative",
        intraday_batch_size=200,
        stop_config=holding_stop_config_from_env(),
        strategy_config=tail_buy_strategy_config_from_env(),
        deadline_at=deadline_at,
        logs_path=None,
    )
    if not holdings:
        print("[holding-diag] no holdings to diagnose")
        return 0

    report = _build_holding_diagnosis_report(
        holdings=holdings,
        portfolio_meta=meta,
        tickflow_limit_hit=limit_hit,
        portfolio_id=runtime.portfolio_id,
        deadline_at=deadline_at,
        started_at=started_at,
    )
    print(report)
    _send_holding_report(report, runtime)
    return 0


def _build_holding_diagnosis_report(
    *,
    holdings,
    portfolio_meta: dict,
    tickflow_limit_hit: bool,
    portfolio_id: str,
    deadline_at: datetime,
    started_at: float,
) -> str:
    rule_section = build_holdings_markdown(
        holdings=holdings,
        portfolio_meta=portfolio_meta,
        tickflow_limit_hit=tickflow_limit_hit,
    )
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
