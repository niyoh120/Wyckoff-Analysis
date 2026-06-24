"""TickFlow market-data fetching for holding action analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from integrations.tickflow_client import TickFlowClient
from integrations.tickflow_notice import is_tickflow_rate_limited_error
from workflows.tail_buy_holding_models import HoldingMarketData
from workflows.tail_buy_utils import chunked, log_line, remaining_seconds, with_tickflow_upgrade_hint


def fetch_holding_market_data(
    *,
    tickflow_client: TickFlowClient,
    symbol_set: list[str],
    intraday_batch_size: int,
    deadline_at: datetime,
    logs_path: str | None,
) -> HoldingMarketData:
    quotes, quote_limit_hit = _fetch_holding_quotes(tickflow_client, symbol_set, logs_path)
    intraday_map, intraday_error_by_symbol, intraday_limit_hit = _fetch_holding_intraday(
        tickflow_client=tickflow_client,
        symbol_set=symbol_set,
        intraday_batch_size=intraday_batch_size,
        deadline_at=deadline_at,
    )
    return HoldingMarketData(
        quotes=quotes,
        intraday_map=intraday_map,
        intraday_error_by_symbol=intraday_error_by_symbol,
        tickflow_limit_hit=quote_limit_hit or intraday_limit_hit,
    )


def _fetch_holding_quotes(
    tickflow_client: TickFlowClient,
    symbol_set: list[str],
    logs_path: str | None,
) -> tuple[dict[str, dict[str, Any]], bool]:
    try:
        return tickflow_client.get_quotes(symbol_set), False
    except Exception as e:
        log_line(f"持仓动作分析: 批量实时行情失败: {e}", logs_path)
        return {}, is_tickflow_rate_limited_error(e)


def _fetch_holding_intraday(
    *,
    tickflow_client: TickFlowClient,
    symbol_set: list[str],
    intraday_batch_size: int,
    deadline_at: datetime,
) -> tuple[dict[str, Any], dict[str, str], bool]:
    intraday_map: dict[str, Any] = {}
    intraday_error_by_symbol: dict[str, str] = {}
    tickflow_limit_hit = False
    for chunk in chunked(symbol_set, max(min(int(intraday_batch_size), 200), 1)):
        if remaining_seconds(deadline_at) <= 5:
            _mark_intraday_timeout(chunk, intraday_error_by_symbol)
            break
        tickflow_limit_hit = (
            _fetch_intraday_chunk(tickflow_client, chunk, intraday_map, intraday_error_by_symbol) or tickflow_limit_hit
        )
    return intraday_map, intraday_error_by_symbol, tickflow_limit_hit


def _mark_intraday_timeout(chunk: list[str], errors: dict[str, str]) -> None:
    for sym in chunk:
        errors[sym] = "超出任务时限，未执行持仓分时分析"


def _fetch_intraday_chunk(
    tickflow_client: TickFlowClient,
    chunk: list[str],
    intraday_map: dict[str, Any],
    errors: dict[str, str],
) -> bool:
    try:
        data_map = tickflow_client.get_intraday_batch(chunk, period="1m", count=5000)
        intraday_map.update(data_map)
        for sym in chunk:
            if sym not in data_map:
                errors[sym] = "TickFlow返回空分时"
        return False
    except Exception as e:
        reason = with_tickflow_upgrade_hint(f"TickFlow持仓分时拉取失败: {e}")
        for sym in chunk:
            errors[sym] = reason
        return is_tickflow_rate_limited_error(e)
