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

    return ToolContext(
        state={
            "user_id": os.getenv("SUPABASE_USER_ID", ""),
            "access_token": os.getenv("SUPABASE_ACCESS_TOKEN", ""),
            "refresh_token": os.getenv("SUPABASE_REFRESH_TOKEN", ""),
        }
    )


_ctx = _build_ctx()


# ---------------------------------------------------------------------------
# Tier 1: 无需凭证 — 纯本地 SQLite 读取
# ---------------------------------------------------------------------------

from agents.chat_tools import query_history as _query_history


@mcp.tool()
def query_history(source: str, status: str = "all", run_date: str = "", decision: str = "", limit: int = 20) -> dict:
    """查询历史记录：形态复盘(recommendation)、信号确认池(signal)或尾盘买入(tail_buy)。"""
    return _query_history(source=source, status=status, run_date=run_date, decision=decision, limit=limit)


# ---------------------------------------------------------------------------
# Tier 2: 需 TUSHARE_TOKEN（env 注入）
# ---------------------------------------------------------------------------

from agents.chat_tools import (
    analyze_stock as _analyze_stock,
)
from agents.chat_tools import (
    get_market_overview as _get_market_overview,
)
from agents.chat_tools import (
    run_backtest as _run_backtest,
)
from agents.chat_tools import (
    screen_stocks as _screen_stocks,
)
from agents.chat_tools import (
    search_stock_by_name as _search_stock_by_name,
)


@mcp.tool()
def search_stock_by_name(keyword: str) -> list[dict]:
    """根据关键词搜索 A 股股票，支持名称、代码、拼音首字母模糊搜索。"""
    return _search_stock_by_name(keyword=keyword, tool_context=_ctx)


@mcp.tool()
def analyze_stock(code: str, mode: str = "diagnose", cost: float = 0.0, days: int = 30) -> dict:
    """分析单只 A 股：mode='diagnose' 做 Wyckoff 诊断，mode='price' 返回近期 OHLCV。"""
    return _analyze_stock(code=code, mode=mode, cost=cost, days=days, tool_context=_ctx)


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
        start=start,
        end=end,
        hold_days=hold_days,
        top_n=top_n,
        board=board,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        tool_context=_ctx,
    )


# ---------------------------------------------------------------------------
# Tier 2+: 引擎直连工具（无需 LLM，返回纯结构数据）
# ---------------------------------------------------------------------------


@mcp.tool()
def market_regime() -> dict:
    """获取 A 股市场水温：regime(RISK_ON/NEUTRAL/RISK_OFF/CRASH/PANIC_REPAIR)、大盘指标和动态阈值。"""
    from datetime import date as _date, timedelta

    from core.wyckoff_engine import FunnelConfig
    from integrations.data_source import fetch_index_hist
    from tools.market_regime import analyze_benchmark_and_tune_cfg

    end = _date.today()
    start = end - timedelta(days=400)
    bench_df = fetch_index_hist("000001", start, end)
    smallcap_df = fetch_index_hist("399006", start, end)
    return analyze_benchmark_and_tune_cfg(bench_df, smallcap_df, FunnelConfig(), breadth=None)


@mcp.tool()
def wyckoff_diagnose(code: str) -> dict:
    """单股 Wyckoff 结构诊断：交易区间(TR)、触发信号(Spring/SOS/LPS/EVR)、阶段和事件分类。纯引擎数据，非 LLM 文本。"""
    import dataclasses
    from datetime import date as _date, timedelta

    from core.stock_cache import normalize_hist_df
    from core.wyckoff_engine import FunnelConfig
    from core.wyckoff_events import classify_wyckoff_event
    from core.wyckoff_v2_structure import detect_structure_triggers, identify_trading_range
    from integrations.stock_hist_repository import get_stock_hist

    end = _date.today()
    start = end - timedelta(days=500)
    raw = get_stock_hist(code, start, end)
    if raw is None or raw.empty:
        return {"error": f"无法获取 {code} 的行情数据"}

    df = normalize_hist_df(raw)
    cfg = FunnelConfig()
    tr = identify_trading_range(df, cfg)
    result = detect_structure_triggers([code], {code: df}, cfg)

    stock_triggers = []
    for trig_type in ("spring", "sos", "lps", "evr"):
        for sym, _score in result.triggers.get(trig_type, []):
            if sym == code:
                stock_triggers.append(trig_type)

    stage = result.stage_map.get(code, "")
    event = classify_wyckoff_event(stock_triggers, stage=stage)

    return {
        "code": code,
        "trading_range": dataclasses.asdict(tr) if tr else None,
        "triggers": stock_triggers,
        "stage": stage,
        "event": dataclasses.asdict(event),
    }


@mcp.tool()
def run_funnel_simulation(board: str = "all") -> dict:
    """运行 Wyckoff 五层漏斗仿真，返回原始结构数据（层计数、触发、阶段、通道、板块、退出信号）。耗时 30-60s。"""
    import os

    os.environ.setdefault("FUNNEL_EXECUTOR_MODE", "thread")
    if board != "all":
        os.environ["FUNNEL_POOL_MODE"] = board

    from core.funnel_pipeline import run_funnel

    ok, symbols, bench_ctx, details = run_funnel("", notify=False, return_details=True)
    if not ok:
        return {"error": "漏斗运行失败", "details": details}
    return {
        "success": True,
        "candidates": symbols,
        "regime": bench_ctx,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Tier 3: 需 Supabase 用户认证
# ---------------------------------------------------------------------------

from agents.chat_tools import (
    generate_ai_report as _generate_ai_report,
)
from agents.chat_tools import (
    generate_strategy_decision as _generate_strategy_decision,
)
from agents.chat_tools import (
    portfolio as _portfolio,
)
from agents.chat_tools import (
    update_portfolio as _update_portfolio,
)


@mcp.tool()
def portfolio(mode: str = "view") -> dict:
    """查看或诊断用户持仓。mode='view' 仅查看，mode='diagnose' 做 Wyckoff 诊断。"""
    return _portfolio(mode=mode, tool_context=_ctx)


@mcp.tool()
def update_portfolio(
    action: str,
    code: str = "",
    name: str = "",
    shares: int = 0,
    cost_price: float = 0,
    buy_dt: str = "",
    free_cash: float = 0,
    table: str = "",
    codes: list[str] = None,
) -> dict:
    """管理持仓(add/update/remove/set_cash)或删除追踪记录(delete_records)。"""
    return _update_portfolio(
        action=action,
        code=code,
        name=name,
        shares=shares,
        cost_price=cost_price,
        buy_dt=buy_dt,
        free_cash=free_cash,
        table=table,
        codes=codes,
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
