"""Rule-based workflow router for the first dynamic workflow iteration."""

from __future__ import annotations

import re

from cli.workflows.models import WorkflowContext

ASK_TOOLS = ("ask_user_question",)

WORKFLOWS: dict[str, WorkflowContext] = {
    "portfolio_review": WorkflowContext(
        name="portfolio_review",
        label="持仓复盘",
        allowed_tools=(
            "portfolio",
            "analyze_stock",
            "get_market_overview",
            "query_history",
            "delegate_to_analysis",
            "delegate_to_trading",
            *ASK_TOOLS,
        ),
        system_hint="当前 workflow 是持仓复盘。先读取或诊断持仓；不要主动跑回测、全市场扫描或写文件。",
    ),
    "backtest": WorkflowContext(
        name="backtest",
        label="策略回测",
        allowed_tools=(
            "run_backtest",
            "check_background_tasks",
            "get_market_history",
            "delegate_to_research",
            *ASK_TOOLS,
        ),
        system_hint="当前 workflow 是策略回测。缺少时间、参数或股票池时先调用 ask_user_question 澄清。",
    ),
    "stock_screen": WorkflowContext(
        name="stock_screen",
        label="选股扫描",
        allowed_tools=(
            "screen_stocks",
            "generate_ai_report",
            "query_history",
            "get_market_overview",
            "get_market_history",
            "delegate_to_research",
            "delegate_to_analysis",
            *ASK_TOOLS,
        ),
        system_hint="当前 workflow 是选股扫描。优先跑筛选或查询候选池；不要读取用户持仓，除非用户明确要求。",
    ),
    "stock_diagnosis": WorkflowContext(
        name="stock_diagnosis",
        label="个股诊断",
        allowed_tools=(
            "search_stock_by_name",
            "analyze_stock",
            "get_market_overview",
            "get_market_history",
            "query_history",
            "delegate_to_analysis",
            *ASK_TOOLS,
        ),
        system_hint="当前 workflow 是个股诊断。围绕用户点名股票分析价格、结构、触发位和失效位。",
    ),
    "general_chat": WorkflowContext(name="general_chat", label="自由对话"),
}


def route_workflow(user_text: str) -> WorkflowContext:
    """Select a bounded workflow for the current turn using conservative rules."""

    text = user_text.lower()
    resumed = _resume_workflow_context(text)
    if resumed:
        return resumed
    if _has_any(text, ("持仓", "仓位", "组合", "我的票", "手里")):
        return WORKFLOWS["portfolio_review"]
    if _has_any(text, ("回测", "backtest", "收益曲线", "参数梯队", "夏普")):
        return WORKFLOWS["backtest"]
    if _has_any(text, ("筛选", "选股", "扫描", "候选", "漏斗", "全市场")):
        return WORKFLOWS["stock_screen"]
    if _looks_like_stock_question(text):
        return WORKFLOWS["stock_diagnosis"]
    return WORKFLOWS["general_chat"]


def build_workflow_system_prompt(workflow: WorkflowContext | None) -> str:
    """Build a concise system prompt suffix for a selected workflow."""

    if not workflow or workflow.is_general:
        return ""
    tools = ", ".join(workflow.allowed_tools)
    return (
        "\n\n<workflow-runtime>\n"
        f"Workflow: {workflow.label} ({workflow.name})\n"
        f"Allowed tools for this turn: {tools}\n"
        f"{workflow.system_hint}\n"
        "If the user goal is underspecified, call ask_user_question instead of guessing.\n"
        "</workflow-runtime>"
    )


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _resume_workflow_context(text: str) -> WorkflowContext | None:
    if "继续 workflow" not in text and "continue workflow" not in text:
        return None
    for name in ("portfolio_review", "backtest", "stock_screen", "stock_diagnosis"):
        workflow = WORKFLOWS[name]
        if name in text or workflow.label in text:
            return workflow
    return WORKFLOWS["general_chat"]


def _looks_like_stock_question(text: str) -> bool:
    if re.search(r"\b\d{6}\b", text) or re.search(r"\b[a-z]{1,5}\.(us|hk)\b", text):
        return True
    return _has_any(text, ("诊断", "分析", "怎么看", "可不可以买", "触发价", "失效位"))
