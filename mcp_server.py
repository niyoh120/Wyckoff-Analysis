# -*- coding: utf-8 -*-
"""Wyckoff MCP Server — 将 Wyckoff 分析能力通过 MCP 协议对外暴露。"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("wyckoff")


# ---------------------------------------------------------------------------
# 全局 ToolContext — 从环境变量构建凭证
# ---------------------------------------------------------------------------

def _build_ctx():
    from cli.tools import ToolContext
    return ToolContext(state={
        "user_id": os.getenv("SUPABASE_USER_ID", ""),
        "access_token": os.getenv("SUPABASE_ACCESS_TOKEN", ""),
        "refresh_token": os.getenv("SUPABASE_REFRESH_TOKEN", ""),
    })


_ctx = _build_ctx()


# ---------------------------------------------------------------------------
# Tier 1: 无需凭证 — 纯本地 SQLite 读取
# ---------------------------------------------------------------------------

from agents.chat_tools import (
    get_recommendation_tracking as _get_recommendation_tracking,
    get_signal_pending as _get_signal_pending,
    get_tail_buy_history as _get_tail_buy_history,
    delete_tracking_records as _delete_tracking_records,
)


@mcp.tool()
def get_recommendation_tracking(limit: int = 20) -> dict:
    """查询最近的 AI 推荐记录及其跟踪表现。"""
    return _get_recommendation_tracking(limit=limit)


@mcp.tool()
def get_signal_pending(status: str = "all", limit: int = 30) -> dict:
    """查询信号确认池中的信号状态（pending/confirmed/expired）。"""
    return _get_signal_pending(status=status, limit=limit)


@mcp.tool()
def get_tail_buy_history(run_date: str = "", decision: str = "", limit: int = 20) -> dict:
    """查询尾盘买入策略的历史执行结果。"""
    return _get_tail_buy_history(run_date=run_date, decision=decision, limit=limit)


@mcp.tool()
def delete_tracking_records(table: str, codes: list[str]) -> dict:
    """删除推荐跟踪或信号确认池中指定股票的记录。"""
    return _delete_tracking_records(table=table, codes=codes)


# ---------------------------------------------------------------------------
# Tier 2: 需 TUSHARE_TOKEN（env 注入）
# ---------------------------------------------------------------------------

from agents.chat_tools import (
    search_stock_by_name as _search_stock_by_name,
    diagnose_stock as _diagnose_stock,
    get_stock_price as _get_stock_price,
    get_market_overview as _get_market_overview,
    screen_stocks as _screen_stocks,
    run_backtest as _run_backtest,
)


@mcp.tool()
def search_stock_by_name(keyword: str) -> list[dict]:
    """根据关键词搜索 A 股股票，支持名称、代码、拼音首字母模糊搜索。"""
    return _search_stock_by_name(keyword=keyword, tool_context=_ctx)


@mcp.tool()
def diagnose_stock(code: str, cost: float = 0.0) -> dict:
    """对单只 A 股做 Wyckoff 结构化健康诊断。"""
    return _diagnose_stock(code=code, cost=cost, tool_context=_ctx)


@mcp.tool()
def get_stock_price(code: str, days: int = 30) -> dict:
    """获取指定股票的近期行情数据（OHLCV）。"""
    return _get_stock_price(code=code, days=days, tool_context=_ctx)


@mcp.tool()
def get_market_overview() -> dict:
    """获取当前 A 股大盘环境概览（上证、深证、创业板指数）。"""
    return _get_market_overview(tool_context=_ctx)


@mcp.tool()
def screen_stocks(board: str = "all") -> dict:
    """运行 Wyckoff 五层漏斗筛选，从全市场筛选结构性机会股票。耗时较长。"""
    return _screen_stocks(board=board, tool_context=_ctx)


@mcp.tool()
def run_backtest(
    start: str = "",
    end: str = "",
    hold_days: int = 10,
    top_n: int = 3,
    board: str = "main_chinext",
    stop_loss_pct: float = -7.0,
    take_profit_pct: float = 18.0,
) -> dict:
    """回测威科夫五层漏斗策略的历史表现。耗时较长（3-10分钟）。"""
    return _run_backtest(
        start=start, end=end, hold_days=hold_days, top_n=top_n,
        board=board, stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct,
        tool_context=_ctx,
    )


# ---------------------------------------------------------------------------
# Tier 3: 需 Supabase 用户认证
# ---------------------------------------------------------------------------

from agents.chat_tools import (
    get_portfolio as _get_portfolio,
    diagnose_portfolio as _diagnose_portfolio,
    update_portfolio as _update_portfolio,
    generate_ai_report as _generate_ai_report,
    generate_strategy_decision as _generate_strategy_decision,
)


@mcp.tool()
def get_portfolio() -> dict:
    """查看用户当前持仓列表和可用资金。"""
    return _get_portfolio(tool_context=_ctx)


@mcp.tool()
def diagnose_portfolio() -> dict:
    """诊断当前用户所有持仓的 Wyckoff 健康状况。"""
    return _diagnose_portfolio(tool_context=_ctx)


@mcp.tool()
def update_portfolio(
    action: str,
    code: str = "",
    name: str = "",
    shares: int = 0,
    cost_price: float = 0,
    buy_dt: str = "",
    free_cash: float = 0,
) -> dict:
    """更新用户持仓（买入/卖出/更新资金）。"""
    return _update_portfolio(
        action=action, code=code, name=name, shares=shares,
        cost_price=cost_price, buy_dt=buy_dt, free_cash=free_cash,
        tool_context=_ctx,
    )


@mcp.tool()
def generate_ai_report(stock_codes: list[str]) -> dict:
    """对指定股票列表生成威科夫三阵营 AI 深度研报。"""
    return _generate_ai_report(stock_codes=stock_codes, tool_context=_ctx)


@mcp.tool()
def generate_strategy_decision() -> dict:
    """生成持仓去留决策和新标的买入策略。"""
    return _generate_strategy_decision(tool_context=_ctx)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    from integrations.local_db import init_db
    init_db()
    mcp.run()


if __name__ == "__main__":
    main()
