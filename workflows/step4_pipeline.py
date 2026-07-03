"""Step4 OMS scheduling workflow shared by daily jobs and manual reruns."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from integrations.fetch_a_share_csv import resolve_trading_window
from integrations.supabase_portfolio import load_portfolio_state
from utils.env import env_bool
from utils.trading_clock import resolve_end_calendar_day
from workflows.step4_rebalancer import run as run_step4

TZ = ZoneInfo("Asia/Shanghai")

STEP4_REASON_MAP = {
    "missing_api_key": "Step4 LLM API Key 缺失",
    "skipped_invalid_portfolio": "用户持仓缺失或格式错误，已跳过",
    "skipped_notify_unconfigured": "OMS 通知通道未配置，已跳过",
    "skipped_idempotency": "今日已运行，已跳过",
    "skipped_no_decisions": "模型未给出有效决策，已跳过",
    "llm_failed": "Step4 模型调用失败",
    "notification_failed": "OMS 通知推送失败",
    "ok": "ok",
}


def now_text() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def log_line(msg: str, logs_path: str | None = None) -> None:
    line = f"[{now_text()}] {msg}"
    print(line, flush=True)
    if logs_path:
        os.makedirs(os.path.dirname(logs_path) or ".", exist_ok=True)
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def latest_trade_date_str() -> str:
    window = resolve_trading_window(end_calendar_day=resolve_end_calendar_day(), trading_days=30)
    return window.end_trade_date.isoformat()


def load_step4_target() -> tuple[dict | None, str]:
    target_user_id = os.getenv("SUPABASE_USER_ID", "").strip()
    if not target_user_id:
        return None, "SUPABASE_USER_ID 未配置"
    portfolio_id = f"USER_LIVE:{target_user_id}"
    state = load_portfolio_state(portfolio_id)
    has_env_fallback = bool(os.getenv("MY_PORTFOLIO_STATE", "").strip())
    if not isinstance(state, dict) and not has_env_fallback:
        return None, f"未匹配到 user_id={target_user_id} 的持仓（{portfolio_id}）"
    return {"user_id": target_user_id, "portfolio_id": portfolio_id}, (
        "ok_supabase" if isinstance(state, dict) else "ok_env_fallback"
    )


def is_confirmed_step4_candidate(item: dict) -> bool:
    values = [
        item.get("status"),
        item.get("signal_status"),
        item.get("confirm_status"),
        item.get("selection_source"),
        item.get("source_type"),
        item.get("tag"),
        item.get("recommend_reason"),
    ]
    text = " ".join(str(v or "").strip().lower() for v in values)
    return "confirmed" in text or "确认" in text


def _step4_candidate_meta(symbols_info: list, step3_springboard_codes: list[str]) -> tuple[list[dict], int]:
    if not step3_springboard_codes:
        return [], 0
    allowed_set = set(step3_springboard_codes)
    require_confirmed = env_bool("STEP4_REQUIRE_CONFIRMED_BUY_CANDIDATE", True)
    selected: list[dict] = []
    blocked = 0
    for item in symbols_info:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        if code not in allowed_set:
            continue
        if require_confirmed and not is_confirmed_step4_candidate(item):
            blocked += 1
            continue
        selected.append(item)
    return selected, blocked if require_confirmed else 0


def run_step4_pipeline(
    *,
    step4_target: dict,
    symbols_info: list,
    step3_springboard_codes: list[str],
    step3_report_text: str,
    benchmark_context: dict | None,
    api_key: str,
    model: str,
    provider: str,
    llm_base_url: str,
    logs_path: str | None,
    holdings_intraday_report: str = "",
) -> dict:
    t0 = datetime.now(TZ)
    tg_bot_token = os.getenv("TG_BOT_TOKEN", "").strip()
    tg_chat_id = os.getenv("TG_CHAT_ID", "").strip()
    if not tg_bot_token or not tg_chat_id:
        log_line("Step4 私人再平衡: 跳过（TG 通知通道未配置）", logs_path)
        return _step4_summary(True, None, 0, "", "", "skipped (TG 通知通道未配置)")

    user_id = str(step4_target.get("user_id", "") or "").strip()
    portfolio_id = str(step4_target.get("portfolio_id", "") or "").strip()
    candidate_meta, blocked_unconfirmed = _step4_candidate_meta(symbols_info, step3_springboard_codes)
    blocked_msg = f"，未二次确认拦截 {blocked_unconfirmed} 只" if blocked_unconfirmed else ""
    log_line(f"Step4 私人再平衡: 候选收口为 Step3 起跳板 {len(candidate_meta)} 只{blocked_msg}", logs_path)
    return _execute_step4_pipeline(
        user_id=user_id,
        portfolio_id=portfolio_id,
        candidate_meta=candidate_meta,
        step3_report_text=step3_report_text,
        benchmark_context=benchmark_context,
        api_key=api_key,
        model=model,
        provider=provider,
        llm_base_url=llm_base_url,
        tg_bot_token=tg_bot_token,
        tg_chat_id=tg_chat_id,
        logs_path=logs_path,
        started_at=t0,
        holdings_intraday_report=holdings_intraday_report,
    )


def _execute_step4_pipeline(
    *,
    user_id: str,
    portfolio_id: str,
    candidate_meta: list[dict],
    step3_report_text: str,
    benchmark_context: dict | None,
    api_key: str,
    model: str,
    provider: str,
    llm_base_url: str,
    tg_bot_token: str,
    tg_chat_id: str,
    logs_path: str | None,
    started_at: datetime,
    holdings_intraday_report: str,
) -> dict:
    try:
        ok, reason = run_step4(
            external_report=step3_report_text if candidate_meta else "",
            benchmark_context=benchmark_context,
            api_key=api_key,
            model=model,
            provider=provider,
            llm_base_url=llm_base_url,
            candidate_meta=candidate_meta,
            portfolio_id=portfolio_id,
            tg_bot_token=tg_bot_token,
            tg_chat_id=tg_chat_id,
            holdings_intraday_report=holdings_intraday_report,
        )
        err = None if ok else STEP4_REASON_MAP.get(reason, reason)
    except Exception as e:
        ok, reason, err = False, "unexpected_exception", str(e)
    elapsed = (datetime.now(TZ) - started_at).total_seconds()
    log_line(
        f"Step4 私人再平衡: user={user_id}, portfolio={portfolio_id}, ok={ok}, reason={reason}, err={err}", logs_path
    )
    return _step4_summary(ok and err is None, err, round(elapsed, 1), user_id, portfolio_id, reason)


def _step4_summary(ok: bool, err: str | None, elapsed_s: float, user_id: str, portfolio_id: str, reason: str) -> dict:
    return {
        "step": "私人再平衡",
        "ok": ok,
        "err": err,
        "elapsed_s": elapsed_s,
        "output": f"user={user_id}, portfolio={portfolio_id}, reason={reason}",
    }
