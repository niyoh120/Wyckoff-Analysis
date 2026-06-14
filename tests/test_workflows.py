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


def test_route_workflow_selects_stock_diagnosis_for_code():
    workflow = route_workflow("300750 现在怎么看？")

    assert workflow.name == "stock_diagnosis"
    assert "analyze_stock" in workflow.allowed_tools


def test_build_workflow_prompt_is_empty_for_general_chat():
    workflow = route_workflow("你好")

    assert workflow.name == "general_chat"
    assert build_workflow_system_prompt(workflow) == ""


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
