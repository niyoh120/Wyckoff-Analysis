"""Wyckoff Agent 工具集合聚合层。"""

from agents.backtest_tools import run_backtest
from agents.diagnosis_tools import analyze_stock
from agents.history_tools import query_history
from agents.market_tools import get_market_history, get_market_overview
from agents.portfolio_tools import portfolio, update_portfolio
from agents.report_tools import generate_ai_report
from agents.screen_tools import screen_stocks
from agents.search_tools import search_stock_by_name
from agents.strategy_tools import generate_strategy_decision

# ---------------------------------------------------------------------------
# 工具列表导出（Web/MCP/CLI 端，不含 exec/read/write/web_fetch）
# ---------------------------------------------------------------------------

WYCKOFF_TOOLS = [
    search_stock_by_name,
    analyze_stock,
    portfolio,
    get_market_overview,
    get_market_history,
    screen_stocks,
    generate_ai_report,
    generate_strategy_decision,
    query_history,
    update_portfolio,
    run_backtest,
]
