"""Step4 portfolio loading and normalization."""

from __future__ import annotations

import json
import logging
import os
import re

from integrations.supabase_portfolio import compute_portfolio_state_signature
from integrations.supabase_portfolio import load_portfolio_state as load_portfolio_state_from_supabase
from workflows.step4_models import PortfolioState, PositionItem

logger = logging.getLogger(__name__)


def load_step4_portfolio_state(portfolio_id: str) -> tuple[PortfolioState, str, str]:
    """
    优先从 Supabase 读取指定 portfolio_id；
    若缺失则回退到 MY_PORTFOLIO_STATE（Action Secret）。
    返回：(PortfolioState, source, state_signature)
    """
    sb_data = load_portfolio_state_from_supabase(portfolio_id)
    if sb_data:
        try:
            portfolio = build_portfolio_from_dict(sb_data)
            state_signature = str(sb_data.get("state_signature", "") or "").strip().lower()
            if not state_signature:
                state_signature = portfolio_state_signature(portfolio)
            return (portfolio, f"supabase:{portfolio_id.lower()}", state_signature)
        except Exception as e:
            raise ValueError(f"Supabase {portfolio_id} 解析失败: {e}") from e
    try:
        portfolio = load_portfolio_from_env("MY_PORTFOLIO_STATE")
        return (portfolio, "env:MY_PORTFOLIO_STATE", portfolio_state_signature(portfolio))
    except Exception as e:
        raise ValueError(f"Supabase {portfolio_id} 未就绪，且 env 持仓不可用: {e}") from e


def build_portfolio_from_dict(data: dict) -> PortfolioState:
    if not isinstance(data, dict):
        raise ValueError("portfolio data 必须是对象")
    free_cash = float(data.get("free_cash", 0.0) or 0.0)
    total_equity_raw = data.get("total_equity")
    total_equity = float(total_equity_raw) if total_equity_raw is not None else None
    positions_raw = data.get("positions", []) or []
    if not isinstance(positions_raw, list):
        raise ValueError("positions 必须是数组")
    return PortfolioState(
        free_cash=free_cash,
        total_equity=total_equity,
        positions=_build_position_items(positions_raw),
    )


def load_portfolio_from_env(env_key: str = "MY_PORTFOLIO_STATE") -> PortfolioState:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        raise ValueError(f"{env_key} 未配置")
    try:
        data = json.loads(raw)
    except Exception as e:
        raise ValueError(f"{env_key} 非法 JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{env_key} 必须是 JSON 对象")
    return build_portfolio_from_dict(data)


def portfolio_state_signature(portfolio: PortfolioState) -> str:
    return compute_portfolio_state_signature(
        portfolio.free_cash,
        [
            {
                "code": p.code,
                "shares": p.shares,
                "cost_price": p.cost,
                "buy_dt": p.buy_dt,
            }
            for p in portfolio.positions
        ],
    )


def _build_position_items(positions_raw: list) -> list[PositionItem]:
    positions: list[PositionItem] = []
    for idx, item in enumerate(positions_raw, start=1):
        if not isinstance(item, dict):
            logger.warning("跳过非法持仓#%s: 非对象", idx)
            continue
        position = _build_position_item(idx, item)
        if position is not None:
            positions.append(position)
    return positions


def _build_position_item(idx: int, item: dict) -> PositionItem | None:
    code = str(item.get("code", "")).strip()
    if not re.fullmatch(r"\d{6}", code):
        logger.warning("跳过非法持仓#%s: code 非6位", idx)
        return None
    return PositionItem(
        code=code,
        name=str(item.get("name", code)).strip() or code,
        cost=float(item.get("cost", 0.0) or 0.0),
        buy_dt=str(item.get("buy_dt", "")).strip(),
        shares=int(item.get("shares", 0) or 0),
        stop_loss=float(item.get("stop_loss")) if item.get("stop_loss") is not None else None,
    )
