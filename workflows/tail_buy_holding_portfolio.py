"""Portfolio loading and normalization for holding action analysis."""

from __future__ import annotations

from typing import Any

from core.constants import TABLE_PORTFOLIOS
from integrations.supabase_base import create_admin_client
from integrations.supabase_portfolio import load_portfolio_state
from workflows.tail_buy_holding_models import HoldingPortfolioContext
from workflows.tail_buy_utils import log_line, normalize_code6, safe_float


def resolve_holding_portfolio_context(portfolio_id: str, logs_path: str | None) -> HoldingPortfolioContext:
    context = _initial_holding_portfolio_context(portfolio_id, logs_path)
    if context.requested_portfolio_id != "USER_LIVE" or context.positions:
        return context
    for candidate_id in _discover_user_live_portfolios(logs_path=logs_path, limit=30):
        fallback_context = _fallback_holding_context(context, candidate_id)
        if fallback_context is None:
            continue
        stats = fallback_context.position_stats
        log_line(
            f"持仓回退命中: requested=USER_LIVE -> resolved={candidate_id}, "
            f"raw={stats['raw']}, active={stats['active']}",
            logs_path,
        )
        return fallback_context
    return context


def holding_no_position_meta(context: HoldingPortfolioContext) -> str:
    stats = context.position_stats
    meta = (
        f"portfolio={context.resolved_portfolio_id}, "
        f"state_sig={(context.state or {}).get('state_signature', '-')}, "
        f"raw_positions={stats['raw']}, active_positions={stats['active']}, "
        f"invalid_code={stats['invalid_code']}, zero_shares={stats['zero_shares']}"
    )
    if context.requested_portfolio_id == "USER_LIVE":
        meta += "（提示：USER_LIVE 无有效仓位；请检查是否应使用 USER_LIVE:<user_id>）"
    return meta


def holding_portfolio_meta(context: HoldingPortfolioContext) -> str:
    stats = context.position_stats
    meta = (
        f"portfolio={context.resolved_portfolio_id}, "
        f"state_sig={(context.state or {}).get('state_signature', '-')}, "
        f"raw_positions={stats['raw']}, active_positions={stats['active']}"
    )
    if context.requested_portfolio_id != context.resolved_portfolio_id:
        meta += f"（fallback from {context.requested_portfolio_id}）"
    return meta


def _fallback_holding_context(
    base_context: HoldingPortfolioContext,
    candidate_id: str,
) -> HoldingPortfolioContext | None:
    fallback_state = load_portfolio_state(candidate_id)
    if not isinstance(fallback_state, dict):
        return None
    fallback_positions, fallback_stats = _normalize_effective_positions(list(fallback_state.get("positions") or []))
    if not fallback_positions:
        return None
    return HoldingPortfolioContext(
        requested_portfolio_id=base_context.requested_portfolio_id,
        resolved_portfolio_id=candidate_id,
        state=fallback_state,
        positions=fallback_positions,
        position_stats=fallback_stats,
    )


def _initial_holding_portfolio_context(portfolio_id: str, logs_path: str | None) -> HoldingPortfolioContext:
    requested_portfolio_id = str(portfolio_id or "").strip() or "USER_LIVE"
    state = load_portfolio_state(requested_portfolio_id)
    positions: list[dict[str, Any]] = []
    position_stats = _empty_position_stats()
    if isinstance(state, dict):
        positions, position_stats = _normalize_effective_positions(list(state.get("positions") or []))
        _log_holding_position_stats(requested_portfolio_id, requested_portfolio_id, position_stats, logs_path)
    elif requested_portfolio_id == "USER_LIVE":
        log_line("持仓读取: USER_LIVE 不存在或读取失败，尝试回退 USER_LIVE:*", logs_path)
    return HoldingPortfolioContext(
        requested_portfolio_id=requested_portfolio_id,
        resolved_portfolio_id=requested_portfolio_id,
        state=state if isinstance(state, dict) else None,
        positions=positions,
        position_stats=position_stats,
    )


def _normalize_effective_positions(raw_positions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    positions: list[dict[str, Any]] = []
    stats = _empty_position_stats()
    for row in raw_positions or []:
        _append_position(row, positions, stats)
    return positions, stats


def _append_position(row: Any, positions: list[dict[str, Any]], stats: dict[str, int]) -> None:
    stats["raw"] += 1
    if not isinstance(row, dict):
        stats["invalid_row"] += 1
        return
    code = normalize_code6(row.get("code"))
    if len(code) != 6:
        stats["invalid_code"] += 1
        return
    shares = int(safe_float(row.get("shares"), 0))
    if shares <= 0:
        stats["zero_shares"] += 1
        return
    stats["active"] += 1
    positions.append(
        {
            "code": code,
            "name": str(row.get("name", "") or code).strip() or code,
            "shares": shares,
            "cost": safe_float(row.get("cost"), 0.0),
            "stop_loss": row.get("stop_loss"),
        }
    )


def _empty_position_stats() -> dict[str, int]:
    return {"raw": 0, "active": 0, "invalid_code": 0, "zero_shares": 0, "invalid_row": 0}


def _discover_user_live_portfolios(logs_path: str | None = None, limit: int = 30) -> list[str]:
    try:
        client = create_admin_client()
        rows = (
            client.table(TABLE_PORTFOLIOS)
            .select("portfolio_id,updated_at")
            .like("portfolio_id", "USER_LIVE:%")
            .order("updated_at", desc=True)
            .limit(max(int(limit), 1))
            .execute()
            .data
            or []
        )
        ids = [str(row.get("portfolio_id", "") or "").strip() for row in rows if isinstance(row, dict)]
        ids = [x for x in ids if x]
        log_line(f"持仓回退候选: USER_LIVE:* count={len(ids)}", logs_path)
        return ids
    except Exception as e:
        log_line(f"持仓回退候选查询失败: {e}", logs_path)
        return []


def _log_holding_position_stats(
    requested_portfolio_id: str,
    resolved_portfolio_id: str,
    position_stats: dict[str, int],
    logs_path: str | None,
) -> None:
    log_line(
        f"持仓读取: requested={requested_portfolio_id}, resolved={resolved_portfolio_id}, "
        f"raw={position_stats['raw']}, active={position_stats['active']}, "
        f"invalid_code={position_stats['invalid_code']}, zero_shares={position_stats['zero_shares']}, "
        f"invalid_row={position_stats['invalid_row']}",
        logs_path,
    )
