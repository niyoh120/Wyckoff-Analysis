"""Candidate loading workflow for the tail-buy intraday job."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from core.constants import TABLE_SIGNAL_PENDING
from core.tail_buy.strategy import TailBuyCandidate, pick_tail_candidates
from integrations.fetch_a_share_csv import resolve_trading_window
from integrations.supabase_base import create_admin_client, is_admin_configured
from integrations.supabase_portfolio import load_portfolio_state
from workflows.tail_buy_utils import current_time, log_line, normalize_code6


def resolve_tail_buy_trade_dates(logs_path: str | None = None) -> tuple[str, str]:
    calendar_today = current_time().date()
    try:
        return _resolve_calendar_trade_dates(calendar_today)
    except Exception as exc:
        prev_trade = (calendar_today - timedelta(days=1)).isoformat()
        today_trade = calendar_today.isoformat()
        log_line(
            f"交易日历解析失败，降级为自然日: prev={prev_trade}, today={today_trade}, err={exc}",
            logs_path,
        )
        return prev_trade, today_trade


def load_tail_candidates(
    target_signal_date: str,
    portfolio_id: str,
    logs_path: str | None = None,
) -> tuple[list[TailBuyCandidate], str]:
    pending = _load_signal_pending_candidates(target_signal_date, logs_path)
    holdings = _load_holding_candidates(portfolio_id, target_signal_date, logs_path)
    pending_codes = {candidate.code for candidate in pending}
    supplement = [candidate for candidate in holdings if candidate.code not in pending_codes]

    merged = pending + supplement
    merged.sort(key=lambda x: (x.status != "confirmed", -x.signal_score, x.code))
    source_desc = (
        f"signal_pending_15d={len(pending)} + holding={len(supplement)} "
        f"(target={target_signal_date}, portfolio={portfolio_id})"
    )
    log_line(
        f"候选池加载完成: signal_pending={len(pending)}, 持仓补充={len(supplement)}, 合计={len(merged)}",
        logs_path,
    )
    return merged, source_desc


def _resolve_calendar_trade_dates(calendar_today: date) -> tuple[str, str]:
    window = resolve_trading_window(end_calendar_day=calendar_today, trading_days=2)
    prev_trade = window.start_trade_date.isoformat()
    today_trade = window.end_trade_date.isoformat()
    if window.end_trade_date < calendar_today:
        prev_trade = today_trade
    return prev_trade, today_trade


def _load_signal_pending_candidates(
    target_signal_date: str,
    logs_path: str | None = None,
    lookback_days: int = 15,
) -> list[TailBuyCandidate]:
    if not is_admin_configured():
        raise RuntimeError("Supabase 凭据未配置，无法读取 signal_pending")

    cutoff_date = _signal_cutoff_date(target_signal_date, lookback_days)
    rows = _fetch_signal_pending_rows(cutoff_date)
    picked = pick_tail_candidates(rows, cutoff_date=cutoff_date)
    log_line(
        f"signal_pending 候选加载: raw={len(rows)}, picked={len(picked)}, "
        f"cutoff={cutoff_date}, target={target_signal_date}",
        logs_path,
    )
    return picked


def _load_holding_candidates(
    portfolio_id: str,
    target_signal_date: str,
    logs_path: str | None = None,
) -> list[TailBuyCandidate]:
    state = load_portfolio_state(portfolio_id)
    positions = state.get("positions", []) if isinstance(state, dict) else []
    candidates = [_holding_candidate(pos, target_signal_date) for pos in positions]
    candidates = [candidate for candidate in candidates if candidate is not None]
    log_line(f"持仓候选加载: portfolio={portfolio_id}, count={len(candidates)}", logs_path)
    return candidates


def _signal_cutoff_date(target_signal_date: str, lookback_days: int) -> str:
    lookback = int(lookback_days * 1.5)
    return (datetime.strptime(target_signal_date, "%Y-%m-%d") - timedelta(days=lookback)).strftime("%Y-%m-%d")


def _fetch_signal_pending_rows(cutoff_date: str) -> list[dict]:
    client = create_admin_client()
    try:
        return (
            client.table(TABLE_SIGNAL_PENDING)
            .select("code,name,signal_type,signal_score,status,signal_date,regime,snap_support,snap_ma20")
            .in_("status", ["pending", "confirmed"])
            .gte("signal_date", cutoff_date)
            .order("signal_date", desc=True)
            .limit(8000)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        raise RuntimeError(f"读取 signal_pending 失败: {exc}") from exc


def _holding_candidate(pos: dict, target_signal_date: str) -> TailBuyCandidate | None:
    code = normalize_code6(pos.get("code"))
    if not code:
        return None
    return TailBuyCandidate(
        code=code,
        name=str(pos.get("name", "") or code).strip() or code,
        signal_date=target_signal_date,
        status="confirmed",
        signal_type="holding",
        signal_score=0.0,
    )
