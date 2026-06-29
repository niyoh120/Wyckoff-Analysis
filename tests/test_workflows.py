from __future__ import annotations

from cli.runtime import AgentRuntime
from cli.tools import TOOL_SCHEMAS
from cli.workflows.dispatch import build_turn_runtime, infer_direct_allowed_tools
from cli.workflows.executor import WorkflowExecutor
from cli.workflows.router import build_workflow_system_prompt, route_workflow
from tests.helpers.agent_loop_harness import ScriptedProvider, StubToolRegistry


class RouterDecisionProvider(ScriptedProvider):
    def __init__(self, decision: str):
        super().__init__([])
        self.decision = decision
        self.chat_calls: list[dict] = []

    def chat(self, messages, tools, system_prompt=""):
        self.chat_calls.append({"messages": messages, "tools": tools, "system_prompt": system_prompt})
        return {"type": "text", "text": self.decision}


def test_route_workflow_keeps_portfolio_turn_direct():
    workflow = route_workflow("我的持仓有没有要处理的？")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"


def test_route_workflow_keeps_task_like_typo_direct_for_model_inference():
    workflow = route_workflow("给我做磁场诊断")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_keeps_single_tool_backtest_direct():
    workflow = route_workflow("帮我回测 2023 年参数")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_keeps_stock_diagnosis_direct():
    workflow = route_workflow("300750 现在怎么看？")

    assert workflow.name == "general_chat"


def test_build_workflow_prompt_is_empty_for_general_chat():
    workflow = route_workflow("你好")

    assert workflow.name == "general_chat"
    assert build_workflow_system_prompt(workflow) == ""
    assert workflow.route_reason == "普通工具型对话交给直接 agent"


def test_workflow_prompt_prefers_model_inference_before_clarifying():
    workflow = route_workflow("用 workflow 给我做磁场诊断")
    prompt = build_workflow_system_prompt(workflow)

    assert "自然语言理解" in prompt
    assert "工具验证" in prompt
    assert "文字形式本身" in prompt
    assert "错别字" not in prompt


def test_ask_user_question_schema_makes_clarification_last_resort():
    schema = next(item for item in TOOL_SCHEMAS if item["name"] == "ask_user_question")

    assert "先根据上下文和工具判断" in schema["description"]
    assert "写入/交易/高风险确认" in schema["description"]
    assert "优先使用" not in schema["description"]


def test_route_workflow_explicit_dynamic_opt_in():
    workflow = route_workflow("用 workflow 帮我研究一下今天的市场风险")

    assert workflow.name == "dynamic_task"
    assert "delegate_to_research" in workflow.allowed_tools
    assert workflow.route_reason == "用户显式要求动态 workflow"


def test_route_workflow_deep_research_opt_in():
    workflow = route_workflow("分阶段深度研究一下今天的市场风险")

    assert workflow.name == "dynamic_task"
    assert workflow.route_reason == "用户要求深度/多阶段研究"
    assert workflow.route_matches == ("深度研究", "分阶段")


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


def test_dispatch_uses_direct_runtime_for_portfolio_turn():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="我的持仓有什么风险？",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)


def test_dispatch_uses_workflow_executor_when_model_routes_complex_natural_turn():
    provider = RouterDecisionProvider(
        '{"mode":"dynamic_workflow","confidence":0.84,"reason":"需要先筛选候选，再分析结构和攻防动作"}'
    )

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我完整做一遍今天的A股选股，给出候选、理由和买卖计划",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_reason == "模型判断需要动态 workflow：需要先筛选候选，再分析结构和攻防动作"
    assert workflow.route_matches == ("model_router",)
    assert isinstance(runtime, WorkflowExecutor)
    assert provider.chat_calls
    assert provider.chat_calls[0]["tools"] == []
    assert "不要按关键词机械判断" in provider.chat_calls[0]["system_prompt"]


def test_dispatch_keeps_direct_runtime_when_model_routes_direct():
    provider = RouterDecisionProvider('{"mode":"direct","confidence":0.9,"reason":"单只股票诊断"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="300750 现在怎么看？",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)


def test_dispatch_keeps_direct_runtime_when_model_router_is_unavailable():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我完整做一遍今天的A股选股，给出候选、理由和买卖计划",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)


def test_direct_runtime_prompt_prefers_model_inference_before_clarifying():
    provider = ScriptedProvider([[{"type": "text_delta", "text": "ok"}]])
    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="磁场这个词是不是错别字？",
    )

    events = list(runtime.run_stream([{"role": "user", "content": "磁场这个词是不是错别字？"}]))

    assert workflow.name == "general_chat"
    assert events[-1]["text"] == "ok"
    prompt = provider.calls[0]["system_prompt"]
    assert "自然语言理解" in prompt
    assert "可用工具验证" in prompt
    assert "写入/交易/高风险确认" in prompt
    assert "谐音" not in prompt


def test_direct_turn_exposes_bounded_tools_without_keyword_gate():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="600519",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)
    assert runtime.allowed_tools
    assert "analyze_stock" in runtime.allowed_tools
    assert "run_backtest" in runtime.allowed_tools
    assert "update_portfolio" in runtime.allowed_tools
    assert "read_file" in runtime.allowed_tools
    assert "web_fetch" in runtime.allowed_tools
    assert "exec_command" in runtime.allowed_tools
    assert "write_file" in runtime.allowed_tools
    assert "execute_skill" not in runtime.allowed_tools


def test_direct_local_task_tools_are_not_keyword_gated():
    tools = infer_direct_allowed_tools("token 在 .env 里，帮我发 pypi patch 版")

    assert "read_file" in tools
    assert "web_fetch" in tools
    assert "write_file" in tools
    assert "exec_command" in tools
    assert "execute_skill" not in tools


def test_dispatch_uses_workflow_executor_for_explicit_dynamic_turn():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="用 workflow 做一个持仓风险复盘",
    )

    assert workflow.name == "dynamic_task"
    assert isinstance(runtime, WorkflowExecutor)


def test_dispatch_uses_direct_runtime_for_natural_task_turn():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="给我做磁场诊断",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)


def test_route_workflow_resume_uses_original_label():
    workflow = route_workflow("继续 workflow wf_1\n类型: 持仓复盘")

    assert workflow.name == "portfolio_review"
    assert workflow.route_reason == "用户明确要求继续已有 workflow"


def test_route_workflow_resume_without_label_stays_dynamic():
    workflow = route_workflow("继续 workflow wf_1")

    assert workflow.name == "dynamic_task"
    assert workflow.route_reason == "用户明确要求继续已有 workflow"
