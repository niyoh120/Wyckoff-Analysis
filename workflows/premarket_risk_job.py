"""Premarket risk workflow orchestration."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from core.premarket_public_brief import generate_public_premarket_brief
from integrations.llm_client import call_llm
from integrations.supabase_market_signal import load_latest_market_signal_daily, upsert_market_signal_daily
from utils.feishu import send_feishu_notification
from utils.trading_clock import is_a_share_trading_day
from workflows.premarket_public_brief_config import public_brief_llm_config_from_env
from workflows.premarket_risk_inputs import (
    build_action_matrix,
    fetch_a50,
    fetch_vix_until_ready,
    judge_regime,
    premarket_risk_config_from_env,
)

TZ = ZoneInfo("Asia/Shanghai")
LogFn = Callable[[str], None]


@dataclass(frozen=True)
class PremarketRiskJobConfig:
    logs_path: str
    webhook: str = ""
    dry_run: bool = False


@dataclass(frozen=True)
class PremarketSnapshot:
    a50: dict
    vix: dict
    regime: str
    reasons: list[str]
    public_brief: dict
    action_lines: list[str]


def default_logs_path() -> str:
    return os.path.join(
        os.getenv("LOGS_DIR", "logs"),
        f"premarket_risk_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.log",
    )


def run_premarket_risk_job(config: PremarketRiskJobConfig) -> int:
    log_line("盘前风控任务开始", config.logs_path)
    snapshot = collect_premarket_snapshot(config.logs_path)
    content = build_premarket_content(snapshot)
    if config.dry_run:
        log_line("--dry-run: 不发送飞书", config.logs_path)
        return 0
    persist_premarket_signal(snapshot, config.logs_path)
    return send_premarket_notification(config.webhook, content, config.logs_path)


def log_line(msg: str, logs_path: str | None = None) -> None:
    line = f"[{now_text()}] {msg}"
    print(line, flush=True)
    if logs_path:
        os.makedirs(os.path.dirname(logs_path) or ".", exist_ok=True)
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def now_text() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def collect_premarket_snapshot(logs_path: str) -> PremarketSnapshot:
    risk_config = premarket_risk_config_from_env()
    a50 = fetch_a50()
    vix = fetch_vix_until_ready(config=risk_config, log=lambda msg: log_line(msg, logs_path))
    regime, reasons = judge_regime(a50, vix, risk_config)
    log_line(f"A50: {json.dumps(a50, ensure_ascii=False)}", logs_path)
    log_line(f"VIX: {json.dumps(vix, ensure_ascii=False)}", logs_path)
    log_line(f"风控结论: regime={regime}, reasons={reasons}", logs_path)
    public_brief = _generate_public_brief(a50, vix, regime, reasons, logs_path)
    action_lines = build_action_matrix(regime)
    log_line("盘前动作开关: " + " | ".join(action_lines[1:]), logs_path)
    return PremarketSnapshot(a50, vix, regime, reasons, public_brief, action_lines)


def build_premarket_content(snapshot: PremarketSnapshot) -> str:
    content_parts = [
        f"**当前北京时间**: {now_text()}",
        f"**结论**: `{snapshot.regime}`",
        f"**公共总结**: {snapshot.public_brief.get('banner_title')}",
        str(snapshot.public_brief.get("banner_message") or ""),
        f"**触发原因**: {'；'.join(snapshot.reasons)}",
        "",
        _source_line("A50", snapshot.a50),
        _source_line("VIX", snapshot.vix),
        "",
    ]
    content_parts.extend(_error_lines(snapshot.a50, snapshot.vix))
    content_parts.extend(snapshot.action_lines)
    content_parts.extend(["", "说明：该任务仅做盘前风控与动作门控建议，不执行选股和下单。"])
    return "\n".join(content_parts)


def build_market_signal_patch(snapshot: PremarketSnapshot) -> dict:
    public_brief = snapshot.public_brief
    return {
        "a50_value_date": snapshot.a50.get("date"),
        "a50_source": snapshot.a50.get("source"),
        "a50_close": snapshot.a50.get("close"),
        "a50_pct_chg": snapshot.a50.get("pct_chg"),
        "vix_value_date": snapshot.vix.get("date"),
        "vix_source": snapshot.vix.get("source"),
        "vix_close": snapshot.vix.get("close"),
        "vix_pct_chg": snapshot.vix.get("pct_chg"),
        "premarket_regime": snapshot.regime,
        "premarket_reasons": snapshot.reasons,
        "banner_title": public_brief.get("banner_title"),
        "banner_message": public_brief.get("banner_message"),
        "banner_tone": public_brief.get("banner_tone"),
        "source_jobs": {"premarket_risk_job": _source_job_payload(public_brief)},
    }


def persist_premarket_signal(snapshot: PremarketSnapshot, logs_path: str) -> None:
    trade_date = premarket_session_trade_date_str()
    if not is_a_share_trading_day(datetime.now(TZ).date()):
        log_line(f"非A股交易日({trade_date})，跳过写库", logs_path)
        return
    db_ok = upsert_market_signal_daily(trade_date, build_market_signal_patch(snapshot))
    log_line(f"市场信号写库(premarket): ok={db_ok}, trade_date={trade_date}, regime={snapshot.regime}", logs_path)


def send_premarket_notification(webhook: str, content: str, logs_path: str) -> int:
    if not webhook:
        log_line("FEISHU_WEBHOOK_URL 未配置，跳过飞书发送", logs_path)
        return 0
    ok = send_feishu_notification(webhook, f"⏰ 盘前风控 {datetime.now(TZ).strftime('%Y-%m-%d')}", content)
    if not ok:
        log_line("飞书发送失败", logs_path)
        return 1
    log_line("飞书发送成功", logs_path)
    return 0


def premarket_session_trade_date_str() -> str:
    return datetime.now(TZ).date().isoformat()


def _load_public_market_signal(logs_path: str | None = None) -> dict:
    try:
        return load_latest_market_signal_daily() or {}
    except Exception as exc:
        log_line(f"读取市场上下文失败，公共简报降级: {exc}", logs_path)
        return {}


def _generate_public_brief(a50: dict, vix: dict, regime: str, reasons: list[str], logs_path: str) -> dict:
    public_brief = generate_public_premarket_brief(
        a50=a50,
        vix=vix,
        regime=regime,
        reasons=reasons,
        market_signal=_load_public_market_signal(logs_path),
        llm_config=public_brief_llm_config_from_env(),
        llm_caller=call_llm,
    )
    log_line(
        "公共盘前简报: "
        f"llm_used={public_brief.get('llm_used')}, provider={public_brief.get('provider')}, "
        f"model={public_brief.get('model')}, title={public_brief.get('banner_title')}",
        logs_path,
    )
    return public_brief


def _source_line(label: str, row: dict) -> str:
    return (
        f"**{label}** ({row.get('source')}): date={row.get('date')}, close={row.get('close')}, pct={row.get('pct_chg')}"
    )


def _error_lines(a50: dict, vix: dict) -> list[str]:
    lines = []
    if not a50.get("ok") and a50.get("error"):
        lines.append(f"**A50注意**: {a50.get('error')}")
    if not vix.get("ok") and vix.get("error"):
        lines.append(f"**VIX注意**: {vix.get('error')}")
    if lines:
        lines.append("")
    return lines


def _source_job_payload(public_brief: dict) -> dict:
    return {
        "updated_at": datetime.now(TZ).isoformat(),
        "writer": "a50_vix_risk",
        "public_brief": {
            "llm_used": public_brief.get("llm_used"),
            "provider": public_brief.get("provider"),
            "model": public_brief.get("model"),
            "validation_reasons": public_brief.get("validation_reasons") or [],
        },
    }
