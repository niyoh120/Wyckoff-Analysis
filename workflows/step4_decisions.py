"""Step4 decision completion, market-data backfill, and execution."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace

from integrations.fetch_a_share_csv import TradingWindow
from workflows.step4_decision_parser import trim_new_buy_decisions
from workflows.step4_models import (
    CandidateMeta,
    DecisionItem,
    ExecutionTicket,
    PortfolioState,
    Step4InputContext,
    Step4OrderConfig,
    Step4RuntimeConfig,
)
from workflows.step4_order_engine import WyckoffOrderEngine
from workflows.step4_payload import calc_atr, fetch_latest_real_close, load_qfq_history

logger = logging.getLogger(__name__)


def rendered_step4_market_view(system_market_view: str, model_market_view: str) -> str:
    if model_market_view and system_market_view:
        return f"{system_market_view} | 模型摘要：{model_market_view}"
    return model_market_view or system_market_view


def complete_step4_decisions(
    decisions: list[DecisionItem],
    portfolio: PortfolioState,
    candidate_meta_map: dict[str, CandidateMeta],
    market_regime: str,
    runtime_config: Step4RuntimeConfig,
) -> list[DecisionItem]:
    mentioned_codes = {d.code for d in decisions}
    for position in portfolio.positions:
        if position.code in mentioned_codes:
            continue
        decisions.append(
            DecisionItem(
                code=position.code,
                name=position.name,
                action="HOLD",
                entry_zone_min=None,
                entry_zone_max=None,
                stop_loss=None,
                trim_ratio=None,
                tape_condition="默认观察",
                invalidate_condition="",
                is_add_on=True,
                reason="模型未给出动作，系统默认 HOLD",
                confidence=None,
            )
        )
    decisions = _attach_candidate_meta(decisions, candidate_meta_map)
    held_codes = {p.code for p in portfolio.positions}
    kept_decisions, dropped, max_new_names = trim_new_buy_decisions(
        decisions,
        held_codes=held_codes,
        market_regime=market_regime,
        limits=runtime_config.new_buy_limits,
    )
    if dropped:
        logger.info(
            "组合级限购生效: regime=%s, max_new_buy_names=%s, dropped=%s",
            market_regime,
            max_new_names,
            ",".join(dropped),
        )
    return _append_rejected_new_buys(
        kept_decisions,
        decisions,
        dropped,
        market_regime=market_regime,
        max_new_names=max_new_names,
    )


def backfill_step4_decision_market_data(
    decisions: list[DecisionItem],
    window: TradingWindow,
    latest_price_map: dict[str, float],
    atr_map: dict[str, float],
    runtime_config: Step4RuntimeConfig,
) -> None:
    missing_codes = [decision.code for decision in decisions if decision.code not in latest_price_map]
    if not missing_codes:
        return
    with ThreadPoolExecutor(max_workers=runtime_config.max_workers) as executor:
        futures = {
            executor.submit(_fetch_step4_decision_market_data, code, window, runtime_config): code
            for code in missing_codes
        }
        for future in as_completed(futures):
            code, atr_v, px = future.result()
            if atr_v is not None:
                atr_map[code] = atr_v
            if px is not None:
                latest_price_map[code] = px


def execute_step4_decisions(
    context: Step4InputContext,
    decisions: list[DecisionItem],
    order_config: Step4OrderConfig,
) -> tuple[list[ExecutionTicket], float]:
    engine = WyckoffOrderEngine(
        total_equity=float(context.total_equity),
        free_cash=context.portfolio.free_cash,
        position_map={p.code: p for p in context.portfolio.positions},
        latest_price_map=context.latest_price_map,
        atr_map=context.atr_map,
        market_regime=context.market_regime,
        config=order_config,
    )
    return engine.process(decisions)


def _attach_candidate_meta(
    decisions: list[DecisionItem],
    meta_map: dict[str, CandidateMeta],
) -> list[DecisionItem]:
    out: list[DecisionItem] = []
    for dec in decisions:
        meta = meta_map.get(dec.code)
        if not meta:
            out.append(dec)
            continue
        out.append(
            replace(
                dec,
                wyckoff_track=meta.track or dec.wyckoff_track,
                wyckoff_stage=meta.stage or dec.wyckoff_stage,
                wyckoff_tag=meta.tag or dec.wyckoff_tag,
                funnel_score=meta.funnel_score if dec.funnel_score is None else dec.funnel_score,
                source_type=meta.source_type or dec.source_type,
                capital_migration_bonus=(
                    meta.capital_migration_bonus if dec.capital_migration_bonus is None else dec.capital_migration_bonus
                ),
            )
        )
    return out


def _append_rejected_new_buys(
    kept_decisions: list[DecisionItem],
    all_decisions: list[DecisionItem],
    dropped_codes: list[str],
    *,
    market_regime: str,
    max_new_names: int,
) -> list[DecisionItem]:
    if not dropped_codes:
        return kept_decisions
    dropped_set = set(dropped_codes)
    reason = f"组合级限购拦截: regime={market_regime}, max_new_buy_names={max_new_names}"
    rejected = [
        replace(dec, system_reject_reason=reason)
        for dec in all_decisions
        if dec.code in dropped_set and dec.action in {"PROBE", "ATTACK"}
    ]
    return kept_decisions + rejected


def _fetch_step4_decision_market_data(
    code: str,
    window: TradingWindow,
    runtime_config: Step4RuntimeConfig,
) -> tuple[str, float | None, float | None]:
    atr_v = None
    try:
        df_qfq = load_qfq_history(
            code,
            window,
            enforce_target_trade_date=runtime_config.enforce_target_trade_date,
        )
        atr_v = calc_atr(df_qfq, runtime_config.atr_period)
    except Exception as e:
        logger.warning("%s ATR 计算异常: %s", code, e)
    latest_close = fetch_latest_real_close(
        code,
        window,
        enforce_target_trade_date=runtime_config.enforce_target_trade_date,
    )
    return code, atr_v, latest_close
