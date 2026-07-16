"""Daily-bar holding diagnosis used before Step4 OMS decisions."""

from __future__ import annotations

from core.wyckoff_engine import FunnelConfig
from workflows.holding_diagnosis_core import (
    build_holding_advices,
    build_holdings_markdown,
    fetch_holding_benchmark,
    fetch_holding_daily_frames,
    holding_portfolio_meta,
    resolve_holding_portfolio_context,
)


def run_step4_holdings_diagnosis(portfolio_id: str, logs_path: str | None, log_fn) -> str:
    context = resolve_holding_portfolio_context(portfolio_id)
    if not context.positions:
        return ""
    try:
        df_map = fetch_holding_daily_frames(context.positions)
        bench_df = fetch_holding_benchmark()
        holdings = build_holding_advices(context.positions, df_map, bench_df, FunnelConfig())
        text = build_holdings_markdown(holdings=holdings, portfolio_meta=holding_portfolio_meta(context))
        log_fn(f"持仓日线诊断: {len(holdings)} positions", logs_path)
        return text
    except Exception as e:
        log_fn(f"持仓日线诊断失败（降级继续）: {e}", logs_path)
        return ""
