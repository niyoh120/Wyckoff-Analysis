"""Minute-level holding diagnosis used before Step4 OMS decisions."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from workflows.step4_pipeline import TZ


def run_step4_holdings_diagnosis(portfolio_id: str, logs_path: str | None, log_fn) -> str:
    tickflow_api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not tickflow_api_key:
        return ""
    from integrations.tickflow_client import TickFlowClient
    from workflows.tail_buy_config import tail_buy_strategy_config_from_env
    from workflows.tail_buy_holdings import (
        analyze_holdings_actions,
        build_holdings_markdown,
    )
    from workflows.tail_buy_runtime import holding_stop_config_from_env

    try:
        tf_client = TickFlowClient(api_key=tickflow_api_key)
        h_list, h_limit, h_meta = analyze_holdings_actions(
            tickflow_client=tf_client,
            portfolio_id=portfolio_id,
            signal_map={},
            style="conservative",
            intraday_batch_size=200,
            stop_config=holding_stop_config_from_env(),
            strategy_config=tail_buy_strategy_config_from_env(),
            deadline_at=datetime.now(TZ) + timedelta(minutes=5),
            logs_path=logs_path,
        )
        text = build_holdings_markdown(
            holdings=h_list,
            portfolio_meta=h_meta,
            tickflow_limit_hit=h_limit,
        )
        log_fn(f"持仓分时诊断: {len(h_list)} positions", logs_path)
        return text
    except Exception as e:
        log_fn(f"持仓分时诊断失败（降级继续）: {e}", logs_path)
        return ""
