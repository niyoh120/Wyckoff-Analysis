"""Models for tail-buy holding action analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.tail_buy.strategy import DECISION_SKIP

HOLDING_ACTION_ADD = "ADD"
HOLDING_ACTION_HOLD = "HOLD"
HOLDING_ACTION_TRIM = "TRIM"


@dataclass
class HoldingAdvice:
    code: str
    name: str
    shares: int = 0
    cost: float = 0.0
    current_price: float = 0.0
    pnl_pct: float = 0.0
    rule_score: float = 0.0
    rule_decision: str = DECISION_SKIP
    action: str = HOLDING_ACTION_HOLD
    reasons: list[str] = field(default_factory=list)
    fetch_error: str = ""
    features: dict[str, Any] = field(default_factory=dict)
    risk_tag: str = ""


@dataclass(frozen=True)
class HoldingPortfolioContext:
    requested_portfolio_id: str
    resolved_portfolio_id: str
    state: dict[str, Any] | None
    positions: list[dict[str, Any]]
    position_stats: dict[str, int]


@dataclass(frozen=True)
class HoldingMarketData:
    quotes: dict[str, dict[str, Any]]
    intraday_map: dict[str, Any]
    intraday_error_by_symbol: dict[str, str]
    tickflow_limit_hit: bool
