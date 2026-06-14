"""Deterministic workflow planner for CLI turns."""

from __future__ import annotations

import uuid

from cli.workflows.models import WorkflowContext, WorkflowRun, WorkflowStep
from cli.workflows.router import route_workflow


def plan_workflow(
    user_text: str,
    *,
    session_id: str = "",
    context: WorkflowContext | None = None,
) -> WorkflowRun:
    """Create a bounded workflow plan for one user turn."""

    context = context or route_workflow(user_text)
    steps = _template_steps(context)
    return WorkflowRun(
        run_id=f"wf_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        user_text=user_text,
        context=context,
        steps=steps,
    )


def _template_steps(context: WorkflowContext) -> list[WorkflowStep]:
    templates = {
        "portfolio_review": [
            ("scope", "读取持仓与资金", ("portfolio",)),
            ("diagnose", "诊断持仓与市场环境", ("portfolio", "analyze_stock", "get_market_overview")),
            ("decision", "形成去留和风险动作", ("delegate_to_trading", "ask_user_question")),
        ],
        "backtest": [
            ("clarify", "确认回测参数", ("ask_user_question",)),
            ("run", "执行回测任务", ("run_backtest",)),
            ("review", "读取任务进度并解释结果", ("check_background_tasks", "get_market_history")),
        ],
        "stock_screen": [
            ("market", "读取市场水温", ("get_market_overview", "get_market_history")),
            ("screen", "运行候选扫描", ("screen_stocks", "query_history")),
            ("rank", "生成候选解释和下一步", ("generate_ai_report", "delegate_to_analysis")),
        ],
        "stock_diagnosis": [
            ("resolve", "识别股票代码", ("search_stock_by_name",)),
            ("diagnose", "诊断个股结构", ("analyze_stock", "get_market_overview", "get_market_history")),
            ("trade_plan", "输出触发位和失效位", ("delegate_to_analysis", "ask_user_question")),
        ],
    }
    raw_steps = templates.get(context.name, [("answer", "直接回答用户问题", ())])
    return [WorkflowStep(step_id=step_id, title=title, tools=tools) for step_id, title, tools in raw_steps]
