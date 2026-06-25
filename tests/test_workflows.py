from __future__ import annotations

from cli.runtime import AgentRuntime
from cli.workflows.dispatch import build_turn_runtime
from cli.workflows.executor import WorkflowExecutor
from cli.workflows.router import build_workflow_system_prompt, route_workflow
from tests.helpers.agent_loop_harness import ScriptedProvider, StubToolRegistry


def test_route_workflow_selects_portfolio_review():
    workflow = route_workflow("我的持仓有没有要处理的？")

    assert workflow.name == "portfolio_review"
    assert "portfolio" in workflow.allowed_tools
    assert "run_backtest" not in workflow.allowed_tools


def test_route_workflow_selects_backtest():
    workflow = route_workflow("帮我回测 2023 年参数")

    assert workflow.name == "backtest"
    assert "run_backtest" in workflow.allowed_tools
    assert workflow.route_reason == "检测到策略回测意图"
    assert workflow.route_matches == ("回测",)
    assert workflow.route_confidence > 0


def test_route_workflow_selects_stock_diagnosis_for_code():
    workflow = route_workflow("300750 现在怎么看？")

    assert workflow.name == "stock_diagnosis"
    assert "analyze_stock" in workflow.allowed_tools
    assert "300750" in workflow.route_matches
    assert "怎么看" in workflow.route_matches


def test_build_workflow_prompt_is_empty_for_general_chat():
    workflow = route_workflow("你好")

    assert workflow.name == "general_chat"
    assert build_workflow_system_prompt(workflow) == ""
    assert workflow.route_reason == "未命中任务型 workflow，保持自由对话"


def test_route_workflow_explicit_dynamic_opt_in():
    workflow = route_workflow("用 workflow 帮我研究一下今天的市场风险")

    assert workflow.name == "dynamic_task"
    assert "delegate_to_research" in workflow.allowed_tools
    assert workflow.route_reason == "用户显式要求动态 workflow"


def test_route_workflow_explaining_workflow_stays_general():
    workflow = route_workflow("解释一下 workflow 是什么")

    assert workflow.name == "general_chat"


def test_dispatch_uses_direct_runtime_for_general_chat():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="你好，解释一下 workflow 是什么",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)


def test_dispatch_uses_workflow_executor_for_task_turn():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="我的持仓有什么风险？",
    )

    assert workflow.name == "portfolio_review"
    assert isinstance(runtime, WorkflowExecutor)


def test_route_workflow_resume_uses_original_label():
    workflow = route_workflow("继续 workflow wf_1\n类型: 持仓复盘")

    assert workflow.name == "portfolio_review"
    assert workflow.route_reason == "用户明确要求继续已有 workflow"
