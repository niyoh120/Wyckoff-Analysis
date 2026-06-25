"""Conservative workflow router for selecting when to enter dynamic workflows."""

from __future__ import annotations

import re
from dataclasses import replace

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
    "dynamic_task": WorkflowContext(
        name="dynamic_task",
        label="动态任务",
        allowed_tools=(
            "search_stock_by_name",
            "analyze_stock",
            "portfolio",
            "get_market_overview",
            "get_market_history",
            "query_history",
            "screen_stocks",
            "run_backtest",
            "check_background_tasks",
            "generate_ai_report",
            "generate_strategy_decision",
            "delegate_to_research",
            "delegate_to_analysis",
            "delegate_to_trading",
            *ASK_TOOLS,
        ),
        system_hint="当前 workflow 是用户显式要求的动态任务。让模型生成 phase/task；缺少关键参数时先澄清。",
    ),
    "general_chat": WorkflowContext(name="general_chat", label="自由对话"),
}


def route_workflow(user_text: str) -> WorkflowContext:
    """Select a bounded workflow for the current turn using conservative rules."""

    text = user_text.lower()
    resumed = _resume_workflow_context(text)
    if resumed:
        return _with_route(resumed, "用户明确要求继续已有 workflow", 0.95, ("继续 workflow",))
    if matches := _explicit_dynamic_workflow_matches(text):
        return _with_route(WORKFLOWS["dynamic_task"], "用户显式要求动态 workflow", 0.96, matches)
    if matches := _matched_keywords(text, ("持仓", "仓位", "组合", "我的票", "手里")):
        return _with_route(WORKFLOWS["portfolio_review"], "检测到持仓复盘意图", 0.9, matches)
    if matches := _matched_keywords(text, ("回测", "backtest", "收益曲线", "参数梯队", "夏普")):
        return _with_route(WORKFLOWS["backtest"], "检测到策略回测意图", 0.9, matches)
    if matches := _matched_keywords(text, ("筛选", "选股", "扫描", "候选", "漏斗", "全市场")):
        return _with_route(WORKFLOWS["stock_screen"], "检测到选股扫描意图", 0.88, matches)
    stock_matches = _stock_question_matches(text)
    if stock_matches:
        return _with_route(WORKFLOWS["stock_diagnosis"], "检测到个股诊断意图", 0.82, stock_matches)
    return _with_route(WORKFLOWS["general_chat"], "未命中任务型 workflow，保持自由对话", 0.0, ())


def build_workflow_system_prompt(workflow: WorkflowContext | None) -> str:
    """Build a concise system prompt suffix for a selected workflow."""

    if not workflow or workflow.is_general:
        return ""
    tools = ", ".join(workflow.allowed_tools)
    route_line = f"Route reason: {workflow.route_reason}\n" if workflow.route_reason else ""
    return (
        "\n\n<workflow-runtime>\n"
        f"Workflow: {workflow.label} ({workflow.name})\n"
        f"{route_line}"
        f"Allowed tools for this turn: {tools}\n"
        f"{workflow.system_hint}\n"
        "If the user goal is underspecified, call ask_user_question instead of guessing.\n"
        "</workflow-runtime>"
    )


def _matched_keywords(text: str, keywords: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(keyword for keyword in keywords if keyword in text)


def _explicit_dynamic_workflow_matches(text: str) -> tuple[str, ...]:
    markers = ("ultracode", "用 workflow", "使用 workflow", "以 workflow", "用动态 workflow", "动态 workflow 跑")
    return tuple(marker for marker in markers if marker in text)


def _with_route(
    workflow: WorkflowContext,
    reason: str,
    confidence: float,
    matches: tuple[str, ...],
) -> WorkflowContext:
    return replace(
        workflow,
        route_reason=reason,
        route_confidence=confidence,
        route_matches=matches,
    )


def _resume_workflow_context(text: str) -> WorkflowContext | None:
    if "继续 workflow" not in text and "continue workflow" not in text:
        return None
    for name in ("portfolio_review", "backtest", "stock_screen", "stock_diagnosis"):
        workflow = WORKFLOWS[name]
        if name in text or workflow.label in text:
            return workflow
    return WORKFLOWS["general_chat"]


def _looks_like_stock_question(text: str) -> bool:
    return bool(_stock_question_matches(text))


def _stock_question_matches(text: str) -> tuple[str, ...]:
    code_matches = tuple(re.findall(r"\b\d{6}\b", text) + re.findall(r"\b[a-z]{1,5}\.(?:us|hk)\b", text))
    keyword_matches = _matched_keywords(text, ("诊断", "分析", "怎么看", "可不可以买", "触发价", "失效位"))
    return code_matches + keyword_matches
