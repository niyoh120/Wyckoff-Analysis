"""Step4 OMS result preparation and persistence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from integrations.supabase_portfolio import (
    cancel_trade_orders,
    save_ai_trade_orders,
    update_position_stops,
    upsert_daily_nav,
)
from utils.trading_clock import CN_TZ
from workflows.step4_models import ExecutionTicket, Step4InputContext, Step4RunOptions

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step4ResultRecord:
    run_id: str
    ticket_rows: list[dict]


def prepare_step4_result_record(
    *,
    portfolio_id: str,
    tickets: list[ExecutionTicket],
    state_signature: str,
) -> Step4ResultRecord:
    update_step4_position_stops(portfolio_id, tickets)
    ticket_rows = build_step4_ticket_rows(tickets)
    log_step4_reject_audit(tickets)
    return Step4ResultRecord(_build_step4_run_id(state_signature), ticket_rows)


def save_step4_orders_and_nav(
    *,
    options: Step4RunOptions,
    context: Step4InputContext,
    run_id: str,
    rendered_market_view: str,
    ticket_rows: list[dict],
    free_cash_after: float,
) -> None:
    if _save_step4_trade_orders(options, context, run_id, rendered_market_view, ticket_rows):
        _cancel_previous_trade_orders(options, context, run_id)
    else:
        logger.warning("AI 订单记录写入失败（已忽略，不阻断流程） | portfolio_id=%s", options.portfolio_id)
    _save_step4_nav_snapshot(options, context, free_cash_after)


def update_step4_position_stops(portfolio_id: str, tickets: list[ExecutionTicket]) -> None:
    updates = [
        {"code": ticket.code, "stop_loss": ticket.effective_stop_loss}
        for ticket in tickets
        if ticket.is_holding and ticket.effective_stop_loss is not None
    ]
    if not updates:
        return
    if update_position_stops(portfolio_id, updates):
        logger.info("已更新 %s 个持仓的止损价 | portfolio_id=%s", len(updates), portfolio_id)
    else:
        logger.error("持仓止损价更新失败 | portfolio_id=%s", portfolio_id)


def build_step4_ticket_rows(tickets: list[ExecutionTicket]) -> list[dict]:
    return [
        {
            "code": ticket.code,
            "name": ticket.name,
            "action": ticket.action,
            "status": ticket.status,
            "shares": ticket.shares,
            "price_hint": ticket.price_hint,
            "amount": ticket.amount,
            "stop_loss": ticket.stop_loss,
            "max_loss": ticket.max_loss,
            "drawdown_ratio": ticket.drawdown_ratio,
            "reason": _ticket_reason(ticket),
            "tape_condition": ticket.tape_condition,
            "invalidate_condition": ticket.invalidate_condition,
            "wyckoff_context": ticket.wyckoff_context,
        }
        for ticket in tickets
    ]


def _ticket_reason(ticket: ExecutionTicket) -> str:
    parts = [ticket.reason]
    if ticket.wyckoff_context:
        parts.append(f"context={ticket.wyckoff_context}")
    if ticket.audit:
        parts.append(f"audit={ticket.audit}")
    return " | ".join(part for part in parts if part).strip()


def log_step4_reject_audit(tickets: list[ExecutionTicket]) -> None:
    for ticket in tickets:
        if ticket.status != "APPROVED":
            logger.info(
                "[reject_audit] code=%s, action=%s, reason=%s, audit=%s, context=%s",
                ticket.code,
                ticket.action,
                ticket.reason,
                ticket.audit,
                ticket.wyckoff_context,
            )
    reject_cnt = sum(1 for ticket in tickets if ticket.status != "APPROVED")
    if reject_cnt:
        logger.info("[reject_audit] summary: rejected=%s, total=%s", reject_cnt, len(tickets))


def _build_step4_run_id(state_signature: str) -> str:
    run_id = datetime.now(CN_TZ).strftime("%Y%m%d_%H%M%S") + "_" + str(uuid4())[:8]
    if state_signature:
        run_id += f"_sig{state_signature.lower()}"
    return run_id


def _save_step4_trade_orders(
    options: Step4RunOptions,
    context: Step4InputContext,
    run_id: str,
    rendered_market_view: str,
    ticket_rows: list[dict],
) -> bool:
    ok = save_ai_trade_orders(
        run_id=run_id,
        portfolio_id=options.portfolio_id,
        model=options.model,
        trade_date=context.trade_date,
        market_view=rendered_market_view,
        orders=ticket_rows,
    )
    if ok:
        logger.info(
            "已写入 AI 订单记录: run_id=%s, count=%s, portfolio_id=%s",
            run_id,
            len(ticket_rows),
            options.portfolio_id,
        )
    return bool(ok)


def _cancel_previous_trade_orders(options: Step4RunOptions, context: Step4InputContext, run_id: str) -> None:
    cancelled = cancel_trade_orders(
        portfolio_id=options.portfolio_id,
        trade_date=context.trade_date,
        exclude_run_id=run_id,
    )
    if cancelled:
        logger.info("已作废同日旧 AI 订单: cancelled=%s, portfolio_id=%s", cancelled, options.portfolio_id)


def _save_step4_nav_snapshot(
    options: Step4RunOptions,
    context: Step4InputContext,
    free_cash_after: float,
) -> None:
    positions_value = max(float(context.total_equity) - float(free_cash_after), 0.0)
    if upsert_daily_nav(
        portfolio_id=options.portfolio_id,
        trade_date=context.trade_date,
        free_cash=float(free_cash_after),
        total_equity=float(context.total_equity),
        positions_value=positions_value,
    ):
        logger.info("已写入 %s 日净值快照: %s", options.portfolio_id, context.trade_date)
    else:
        logger.warning("%s 日净值快照写入失败（已忽略）", options.portfolio_id)
