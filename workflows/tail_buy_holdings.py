"""Holding intraday action analysis shared by tail-buy and OMS jobs."""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime
from typing import Any

from core.tail_buy.strategy import (
    DECISION_BUY,
    DECISION_SKIP,
    DECISION_WATCH,
    TailBuyCandidate,
    TailBuyStrategyConfig,
    compute_tail_features,
    score_tail_features,
)
from integrations.tickflow_client import TickFlowClient, normalize_cn_symbol
from workflows.tail_buy_holding_data import fetch_holding_market_data
from workflows.tail_buy_holding_models import (
    HOLDING_ACTION_ADD,
    HOLDING_ACTION_HOLD,
    HOLDING_ACTION_TRIM,
    HoldingAdvice,
    HoldingMarketData,
)
from workflows.tail_buy_holding_portfolio import (
    holding_no_position_meta,
    holding_portfolio_meta,
    resolve_holding_portfolio_context,
)
from workflows.tail_buy_utils import TICKFLOW_UPGRADE_HINT, log_line, resolve_quote_price, safe_float

TAIL_BUY_TRIM_WEAK_LOSS_PCT = -abs(float(os.getenv("TAIL_BUY_TRIM_WEAK_LOSS_PCT", "2.0")))


def _resolve_effective_stop(cost: float, stop_loss: Any, hard_stop_pct: float) -> float:
    stops = []
    explicit_stop = safe_float(stop_loss, 0.0)
    if explicit_stop > 0:
        stops.append(explicit_stop)
    if cost > 0 and hard_stop_pct > 0:
        stops.append(cost * (1 - hard_stop_pct / 100.0))
    if not stops:
        return 0.0
    return max(stops)


def _dedupe_texts(values: list[str], limit: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= max(int(limit), 1):
            break
    return out


def _base_holding_advice(
    position: dict[str, Any],
    quotes: dict[str, dict[str, Any]],
    hard_stop_pct: float,
) -> tuple[HoldingAdvice, str, float]:
    code = position["code"]
    sym = normalize_cn_symbol(code)
    cost = safe_float(position.get("cost"), 0.0)
    quote = quotes.get(sym) or {}
    price = resolve_quote_price(quote)
    pnl_pct = ((price / cost - 1.0) * 100.0) if price > 0 and cost > 0 else 0.0
    advice = HoldingAdvice(
        code=code,
        name=position["name"],
        shares=int(safe_float(position.get("shares"), 0)),
        cost=cost,
        current_price=price,
        pnl_pct=pnl_pct,
    )
    effective_stop = _resolve_effective_stop(cost, position.get("stop_loss"), hard_stop_pct)
    return advice, sym, effective_stop


def _apply_missing_intraday_advice(advice: HoldingAdvice, fetch_error: str, effective_stop: float) -> None:
    advice.fetch_error = fetch_error or "持仓分时缺失"
    advice.rule_decision = DECISION_WATCH
    advice.rule_score = 0.0
    advice.action = HOLDING_ACTION_HOLD
    advice.reasons = _dedupe_texts(["分时数据缺失，先维持观察", advice.fetch_error], limit=2)
    if advice.current_price > 0 and effective_stop > 0 and advice.current_price <= effective_stop:
        advice.action = HOLDING_ACTION_TRIM
        advice.reasons = _dedupe_texts(
            [f"现价{advice.current_price:.2f}跌破风控位{effective_stop:.2f}", advice.fetch_error],
            limit=2,
        )


def _signal_is_actionable(signal_item: TailBuyCandidate | None, signal_type: str) -> bool:
    return signal_item is not None and signal_type.strip().lower() not in {"", "holding", "unknown"}


def _apply_scored_holding_advice(
    *,
    advice: HoldingAdvice,
    df_1m: Any,
    signal_item: TailBuyCandidate | None,
    style: str,
    effective_stop: float,
    strategy_config: TailBuyStrategyConfig,
) -> None:
    signal_score = safe_float(signal_item.signal_score, 0.0) if signal_item else 0.0
    signal_type = str(signal_item.signal_type if signal_item else "")
    status = str(signal_item.status if signal_item else "pending")
    features = compute_tail_features(df_1m, config=strategy_config)
    score, decision, reasons = score_tail_features(
        features,
        signal_score=signal_score,
        signal_type=signal_type,
        status=status,
        style=style,
        config=strategy_config,
    )
    if advice.current_price <= 0:
        advice.current_price = safe_float(features.get("last_close"), 0.0)
        advice.pnl_pct = (
            (advice.current_price / advice.cost - 1.0) * 100.0 if advice.current_price > 0 and advice.cost > 0 else 0.0
        )
    advice.rule_score = score
    advice.rule_decision = decision
    advice.features = features
    _resolve_scored_holding_action(advice, features, decision, reasons, signal_item, signal_type, effective_stop)


def _resolve_scored_holding_action(
    advice: HoldingAdvice,
    features: dict[str, Any],
    decision: str,
    reasons: list[str],
    signal_item: TailBuyCandidate | None,
    signal_type: str,
    effective_stop: float,
) -> None:
    dist_vwap_pct = safe_float(features.get("dist_vwap_pct"), 0.0)
    close_pos = safe_float(features.get("close_pos"), 0.0)
    last30_ret_pct = safe_float(features.get("last30_ret_pct"), 0.0)
    drop_from_high_pct = safe_float(features.get("drop_from_high_pct"), 0.0)
    weak_tail = dist_vwap_pct <= -0.6 or close_pos < 0.42 or last30_ret_pct <= -0.8 or drop_from_high_pct <= -2.2
    severe_tail = (dist_vwap_pct <= -1.0 and close_pos < 0.35) or drop_from_high_pct <= -2.8
    base_reasons = _dedupe_texts(reasons, limit=2)
    if advice.current_price > 0 and effective_stop > 0 and advice.current_price <= effective_stop:
        advice.action = HOLDING_ACTION_TRIM
        advice.reasons = _dedupe_texts(
            [f"现价{advice.current_price:.2f}跌破风控位{effective_stop:.2f}", *base_reasons], limit=3
        )
    elif (
        decision == DECISION_BUY
        and _signal_is_actionable(signal_item, signal_type)
        and dist_vwap_pct >= 0.15
        and close_pos >= 0.68
        and last30_ret_pct >= 0.2
    ):
        advice.action = HOLDING_ACTION_ADD
        advice.reasons = _dedupe_texts(["尾盘结构延续走强，可考虑小幅加仓", *base_reasons], limit=3)
    elif decision == DECISION_SKIP and weak_tail and (advice.pnl_pct <= TAIL_BUY_TRIM_WEAK_LOSS_PCT or severe_tail):
        advice.action = HOLDING_ACTION_TRIM
        advice.reasons = _dedupe_texts(["尾盘结构转弱，优先减仓控制回撤", *base_reasons], limit=3)
    else:
        advice.action = HOLDING_ACTION_HOLD
        hold_reason = "结构中性，先持有观察"
        if decision == DECISION_BUY and not _signal_is_actionable(signal_item, signal_type):
            hold_reason = "无有效L4信号，不做尾盘加仓"
        elif decision == DECISION_BUY:
            hold_reason = "尾盘强度未达加仓触发线，先持有观察"
        advice.reasons = _dedupe_texts([hold_reason, *base_reasons], limit=3)


def _build_holding_advice(
    *,
    position: dict[str, Any],
    market_data: HoldingMarketData,
    signal_map: dict[str, TailBuyCandidate],
    style: str,
    hard_stop_pct: float,
    strategy_config: TailBuyStrategyConfig,
) -> HoldingAdvice:
    advice, sym, effective_stop = _base_holding_advice(position, market_data.quotes, hard_stop_pct)
    df_1m = market_data.intraday_map.get(sym)
    fetch_error = str(market_data.intraday_error_by_symbol.get(sym, "") or "").strip()
    if df_1m is None or getattr(df_1m, "empty", True):
        _apply_missing_intraday_advice(advice, fetch_error, effective_stop)
        return advice
    _apply_scored_holding_advice(
        advice=advice,
        df_1m=df_1m,
        signal_item=signal_map.get(advice.code),
        style=style,
        effective_stop=effective_stop,
        strategy_config=strategy_config,
    )
    return advice


def _build_holding_advices(
    *,
    positions: list[dict[str, Any]],
    market_data: HoldingMarketData,
    signal_map: dict[str, TailBuyCandidate],
    style: str,
    hard_stop_pct: float,
    strategy_config: TailBuyStrategyConfig,
) -> list[HoldingAdvice]:
    out = [
        _build_holding_advice(
            position=position,
            market_data=market_data,
            signal_map=signal_map,
            style=style,
            hard_stop_pct=hard_stop_pct,
            strategy_config=strategy_config,
        )
        for position in positions
    ]
    rank = {HOLDING_ACTION_ADD: 0, HOLDING_ACTION_TRIM: 1, HOLDING_ACTION_HOLD: 2}
    out.sort(key=lambda x: (rank.get(x.action, 9), -x.rule_score, x.code))
    return out


def analyze_holdings_actions(
    *,
    tickflow_client: TickFlowClient,
    portfolio_id: str,
    signal_map: dict[str, TailBuyCandidate],
    style: str,
    intraday_batch_size: int,
    hard_stop_pct: float,
    strategy_config: TailBuyStrategyConfig,
    deadline_at: datetime,
    logs_path: str | None = None,
) -> tuple[list[HoldingAdvice], bool, str]:
    context = resolve_holding_portfolio_context(portfolio_id, logs_path)
    if not isinstance(context.state, dict):
        return [], False, f"组合 {context.requested_portfolio_id} 不存在或不可读取"
    if not context.positions:
        return [], False, holding_no_position_meta(context)

    symbols = [normalize_cn_symbol(p["code"]) for p in context.positions]
    symbol_set = sorted({s for s in symbols if s})
    log_line(
        f"持仓动作分析开始: requested={context.requested_portfolio_id}, resolved={context.resolved_portfolio_id}, "
        f"positions={len(context.positions)}, symbols={len(symbol_set)}",
        logs_path,
    )

    market_data = fetch_holding_market_data(
        tickflow_client=tickflow_client,
        symbol_set=symbol_set,
        intraday_batch_size=intraday_batch_size,
        deadline_at=deadline_at,
        logs_path=logs_path,
    )
    out = _build_holding_advices(
        positions=context.positions,
        market_data=market_data,
        signal_map=signal_map,
        style=style,
        hard_stop_pct=hard_stop_pct,
        strategy_config=strategy_config,
    )
    add_count = sum(1 for advice in out if advice.action == HOLDING_ACTION_ADD)
    trim_count = sum(1 for advice in out if advice.action == HOLDING_ACTION_TRIM)
    log_line(
        f"持仓动作分析完成: total={len(out)}, add={add_count}, trim={trim_count}, "
        f"hold={len(out) - add_count - trim_count}, tickflow_limit_hit={market_data.tickflow_limit_hit}",
        logs_path,
    )
    return out, market_data.tickflow_limit_hit, holding_portfolio_meta(context)


def build_holdings_markdown(
    *,
    holdings: list[HoldingAdvice],
    portfolio_meta: str,
    tickflow_limit_hit: bool,
) -> str:
    lines: list[str] = ["## 持仓动作建议（加仓/减仓）"]
    if portfolio_meta:
        lines.append(f"- 持仓来源: {portfolio_meta}")

    if not holdings:
        lines.append("- 持仓数量: 0")
        lines.append("- 动作分布: ADD=0 / HOLD=0 / TRIM=0")
        lines.append("- 无可分析持仓（仅输出候选池结果）")
        lines.append("")
        lines.append("说明：持仓动作仅为盘中辅助建议，不自动下单。")
        return "\n".join(lines)

    counter = Counter([x.action for x in holdings])
    lines.append(f"- 持仓数量: {len(holdings)}")
    lines.append(
        f"- 动作分布: ADD={counter.get(HOLDING_ACTION_ADD, 0)} / "
        f"HOLD（持有观察）={counter.get(HOLDING_ACTION_HOLD, 0)} / "
        f"TRIM（减仓）={counter.get(HOLDING_ACTION_TRIM, 0)}"
    )
    if tickflow_limit_hit:
        lines.append(f"- ⚠️ {TICKFLOW_UPGRADE_HINT}")
    lines.append("")

    def _append_block(title: str, action: str) -> None:
        block = [x for x in holdings if x.action == action]
        lines.append(f"### {title}")
        if not block:
            lines.append("- 无")
            lines.append("")
            return
        for item in block:
            reasons = "；".join(_dedupe_texts(item.reasons, limit=2)) or "结构中性"
            current = f"{item.current_price:.2f}" if item.current_price > 0 else "--"
            pnl = f"{item.pnl_pct:+.1f}%" if item.current_price > 0 and item.cost > 0 else "--"
            lines.append(
                f"- {item.code} {item.name} | 持仓={item.shares}股 | 现价={current} | "
                f"浮盈={pnl} | 规则={item.rule_decision}({item.rule_score:.1f}) | {reasons}"
            )
        lines.append("")

    _append_block("ADD（可考虑加仓）", HOLDING_ACTION_ADD)
    _append_block("TRIM（可考虑减仓）", HOLDING_ACTION_TRIM)
    _append_block("HOLD（持有观察）", HOLDING_ACTION_HOLD)
    lines.append("说明：持仓动作仅为盘中辅助建议，不自动下单。")
    return "\n".join(lines)
