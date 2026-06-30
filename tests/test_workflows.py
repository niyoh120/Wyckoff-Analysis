from __future__ import annotations

from cli.__main__ import _workflow_step_cli_line
from cli.runtime import AgentRuntime
from cli.tools import TOOL_SCHEMAS
from cli.workflows.dispatch import build_turn_runtime, infer_direct_allowed_tools
from cli.workflows.executor import WorkflowExecutor
from cli.workflows.model_router import _ROUTER_SYSTEM_PROMPT
from cli.workflows.planner import plan_workflow
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


def test_workflow_step_cli_line_includes_agent_and_tool_scope():
    line = _workflow_step_cli_line(
        {
            "status": "completed",
            "title": "读取持仓",
            "agent": "analysis",
            "tool_scope": ["portfolio", "analyze_stock"],
            "summary": "analysis: completed",
        }
    )

    assert "[completed] 读取持仓" in line
    assert "analysis tools=portfolio,analyze_stock" in line
    assert "analysis: completed" in line


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
    assert "合理推断" in prompt
    assert "按假设执行" in prompt
    assert "关键对象仍缺失" in prompt
    assert "错别字" not in prompt


def test_ask_user_question_schema_makes_clarification_last_resort():
    schema = next(item for item in TOOL_SCHEMAS if item["name"] == "ask_user_question")

    assert "先根据上下文和工具判断" in schema["description"]
    assert "表述偏差" in schema["description"]
    assert "先按假设执行并说明" in schema["description"]
    assert "写入/交易/高风险确认" in schema["description"]
    assert "优先使用" not in schema["description"]


def test_screen_stocks_schema_exposes_optional_scan_limit():
    schema = next(item for item in TOOL_SCHEMAS if item["name"] == "screen_stocks")
    limit = schema["parameters"]["properties"]["limit"]

    assert limit["type"] == "integer"
    assert limit["maximum"] == 3000
    assert "快速试扫" in limit["description"]
    assert "全量扫描请不要传" in limit["description"]


def test_route_workflow_explicit_dynamic_opt_in():
    workflow = route_workflow("用 workflow 帮我研究一下今天的市场风险")

    assert workflow.name == "dynamic_task"
    assert "delegate_to_research" in workflow.allowed_tools
    assert workflow.route_reason == "用户显式要求动态 workflow"


def test_route_workflow_leaves_deep_research_to_model_router():
    workflow = route_workflow("分阶段深度研究一下今天的市场风险")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


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
    router_prompt = provider.chat_calls[0]["system_prompt"]
    assert "runtime router" in router_prompt
    assert "默认用 direct" in router_prompt
    assert "查看持仓" not in router_prompt
    assert "单只股票诊断" not in router_prompt


def test_model_router_prompt_is_minimal_runtime_contract():
    assert "默认用 direct" in _ROUTER_SYSTEM_PROMPT
    assert "dynamic_workflow" in _ROUTER_SYSTEM_PROMPT
    assert "不改写" in _ROUTER_SYSTEM_PROMPT
    assert "用户只是" not in _ROUTER_SYSTEM_PROMPT
    assert "一个清楚目标" not in _ROUTER_SYSTEM_PROMPT
    assert "用户表达不标准" not in _ROUTER_SYSTEM_PROMPT
    assert "语义恢复" not in _ROUTER_SYSTEM_PROMPT
    assert "措辞恢复" not in _ROUTER_SYSTEM_PROMPT
    assert "口语、省略、别字" not in _ROUTER_SYSTEM_PROMPT
    assert "错别字" not in _ROUTER_SYSTEM_PROMPT
    assert "谐音" not in _ROUTER_SYSTEM_PROMPT
    assert "查看持仓" not in _ROUTER_SYSTEM_PROMPT
    assert "单只股票诊断" not in _ROUTER_SYSTEM_PROMPT


def test_dispatch_accepts_semantic_model_router_aliases():
    provider = RouterDecisionProvider('{"route":"动态工作流","score":"84%","reason":"需要多阶段筛选和攻防计划"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我完整做一遍今天的A股选股，给出候选、理由和买卖计划",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_reason == "模型判断需要动态 workflow：需要多阶段筛选和攻防计划"
    assert workflow.route_confidence == 0.84
    assert workflow.route_matches == ("model_router",)
    assert isinstance(runtime, WorkflowExecutor)


def test_dispatch_accepts_boolean_workflow_router_flag():
    provider = RouterDecisionProvider('{"workflow":true,"probability":88,"reason":"需要完整研究链路"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="研究一下今天哪些方向值得重点跟踪",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_confidence == 0.88
    assert workflow.route_reason == "模型判断需要动态 workflow：需要完整研究链路"
    assert isinstance(runtime, WorkflowExecutor)


def test_dispatch_uses_streaming_router_when_chat_is_unimplemented():
    provider = ScriptedProvider(
        [[{"type": "text_delta", "text": '{"mode":"dynamic_workflow","confidence":0.82,"reason":"需要多阶段选股"}'}]]
    )
    provider.use_chat_stream_for_routing = True

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我完整做一遍今天的A股选股",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_confidence == 0.82
    assert workflow.route_reason == "模型判断需要动态 workflow：需要多阶段选股"
    assert isinstance(runtime, WorkflowExecutor)
    assert provider.calls[0]["tools"] == []
    assert "runtime router" in provider.calls[0]["system_prompt"]


def test_dispatch_keeps_direct_runtime_when_model_routes_direct():
    provider = RouterDecisionProvider('{"mode":"direct","confidence":0.9,"reason":"单只股票诊断"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="300750 现在怎么看？",
    )

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "模型判断直接处理：单只股票诊断"
    assert isinstance(runtime, AgentRuntime)


def test_dispatch_model_can_override_explicit_workflow_marker_to_direct():
    provider = RouterDecisionProvider('{"mode":"direct","confidence":0.93,"reason":"只是解释概念"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="用 workflow 解释一下 workflow 是什么",
    )

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "模型判断直接处理：只是解释概念"
    assert isinstance(runtime, AgentRuntime)


def test_dispatch_respects_low_confidence_dynamic_decision():
    provider = RouterDecisionProvider('{"mode":"dynamic_workflow","confidence":0.51,"reason":"可能需要多阶段"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="分阶段看看这个概念怎么理解",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_reason == "模型判断需要动态 workflow：可能需要多阶段"
    assert workflow.route_confidence == 0.51
    assert isinstance(runtime, WorkflowExecutor)


def test_dispatch_treats_confidence_as_diagnostic_only():
    provider = RouterDecisionProvider('{"mode":"dynamic_workflow","reason":"模型认为需要拆分"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我完整复盘持仓，再给出攻防计划",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_confidence == 0.0
    assert workflow.route_reason == "模型判断需要动态 workflow：模型认为需要拆分"
    assert isinstance(runtime, WorkflowExecutor)


def test_dispatch_resume_workflow_bypasses_model_router():
    provider = RouterDecisionProvider('{"mode":"direct","confidence":0.99,"reason":"看起来像普通文本"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="继续 workflow wf_1",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_reason == "用户明确要求继续已有 workflow"
    assert provider.chat_calls == []
    assert isinstance(runtime, WorkflowExecutor)


def test_dispatch_accepts_semantic_direct_router_alias():
    provider = RouterDecisionProvider('{"mode":"直接回答","confidence":"95%","reason":"单轮问题"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="解释一下 workflow 是什么",
    )

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "模型判断直接处理：单轮问题"
    assert workflow.route_confidence == 0.95
    assert workflow.route_matches == ("model_router",)
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
    assert workflow.route_reason == "模型路由不可用（无路由响应），直接 agent 处理"
    assert workflow.route_matches == ("model_router_fallback",)


def test_dispatch_surfaces_invalid_model_router_json():
    provider = RouterDecisionProvider("这不是 JSON")

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我完整做一遍今天的A股选股，给出候选、理由和买卖计划",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)
    assert workflow.route_reason == "模型路由不可用（路由 JSON 无效），直接 agent 处理"
    assert workflow.route_matches == ("model_router_fallback",)


def test_dispatch_keeps_explicit_workflow_when_model_router_is_unavailable():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="用 workflow 做一个持仓风险复盘",
    )

    assert workflow.name == "dynamic_task"
    assert isinstance(runtime, WorkflowExecutor)
    assert workflow.route_reason == "模型路由不可用（无路由响应），沿用兜底路由：用户显式要求动态 workflow"
    assert workflow.route_matches == ("model_router_fallback", "用 workflow")


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
    assert "上下文恢复" in prompt
    assert "可用工具验证" in prompt
    assert "合理推断" in prompt
    assert "说明假设" in prompt
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


def test_planner_ignores_agent_role_and_keeps_exact_tools():
    context = route_workflow("用 workflow 生成交易决策")
    run = plan_workflow(
        "生成交易决策",
        context=context,
        workflow_script={
            "phases": [
                {
                    "tasks": [
                        {
                            "id": "decision",
                            "title": "生成交易决策",
                            "agent": "research",
                            "tools": ["generate_strategy_decision"],
                            "prompt": "基于候选和持仓输出攻防动作。",
                        }
                    ]
                }
            ]
        },
    )
    role_only = plan_workflow(
        "读取市场事实",
        context=context,
        workflow_script={"phases": [{"tasks": [{"id": "facts", "title": "读取市场事实", "agent": "research"}]}]},
    )

    assert run.steps[0].agent == "task"
    assert run.steps[0].tools == ()
    assert run.steps[0].tool_scope == ("generate_strategy_decision",)
    assert role_only.steps[0].agent == "task"
    assert role_only.steps[0].tools == ()


def test_planner_ignores_semantic_tool_labels():
    context = route_workflow("用 workflow 做持仓和选股复盘")
    run = plan_workflow(
        "做持仓和选股复盘",
        context=context,
        workflow_script={
            "phases": [
                {
                    "tasks": [
                        {
                            "id": "facts",
                            "title": "读取事实",
                            "tools": ["持仓", "screen_stocks", {"display_name": "提问用户"}],
                            "prompt": "读取持仓、筛选候选；只有对象仍不明确时再问用户。",
                        }
                    ]
                }
            ]
        },
    )

    assert run.steps[0].agent == "task"
    assert run.steps[0].tool_scope == ("screen_stocks",)


def test_planner_normalizes_tool_suffixes_from_model_script():
    context = route_workflow("用 workflow 做持仓复盘")
    run = plan_workflow(
        "做持仓复盘",
        context=context,
        workflow_script={
            "phases": [
                {
                    "tasks": [
                        {
                            "id": "portfolio",
                            "title": "读取持仓",
                            "tools": ["portfolio tool", "持仓工具", {"name": "查看持仓"}],
                            "prompt": "读取真实持仓。",
                        }
                    ]
                }
            ]
        },
    )

    assert run.steps[0].tool_scope == ("portfolio",)


def test_planner_accepts_string_task_lists_from_model_script():
    context = route_workflow("用 workflow 做持仓复盘")
    run = plan_workflow(
        "做持仓复盘",
        context=context,
        workflow_script={"tasks": ["读取真实持仓", "诊断持仓风险"]},
    )

    assert [step.step_id for step in run.steps] == ["1", "2"]
    assert [step.title for step in run.steps] == ["读取真实持仓", "诊断持仓风险"]
    assert [step.prompt for step in run.steps] == ["读取真实持仓", "诊断持仓风险"]
    assert all(step.dynamic for step in run.steps)


def test_planner_accepts_keyed_string_task_maps_from_model_script():
    context = route_workflow("用 workflow 做持仓复盘")
    run = plan_workflow(
        "做持仓复盘",
        context=context,
        workflow_script={"tasks": {"facts": "读取真实持仓", "risk": "诊断持仓风险"}},
    )

    assert [step.step_id for step in run.steps] == ["facts", "risk"]
    assert [step.title for step in run.steps] == ["读取真实持仓", "诊断持仓风险"]


def test_planner_accepts_plan_field_from_model_script():
    context = route_workflow("用 workflow 做持仓复盘")
    run = plan_workflow(
        "做持仓复盘",
        context=context,
        workflow_script={"plan": ["读取真实持仓", "诊断持仓风险"]},
    )

    assert [step.step_id for step in run.steps] == ["1", "2"]
    assert [step.title for step in run.steps] == ["读取真实持仓", "诊断持仓风险"]


def test_planner_wraps_top_level_json_task_array():
    provider = ScriptedProvider(
        [
            [
                {
                    "type": "text_delta",
                    "text": '["读取真实持仓", {"id":"risk","title":"诊断持仓风险"}]',
                }
            ]
        ]
    )
    context = route_workflow("用 workflow 做持仓复盘")
    run = plan_workflow("做持仓复盘", context=context, provider=provider, tools=StubToolRegistry())

    assert [step.step_id for step in run.steps] == ["1", "risk"]
    assert [step.title for step in run.steps] == ["读取真实持仓", "诊断持仓风险"]
    assert run.script["rationale"] == "planner returned top-level task list"


def test_planner_parses_outline_text_when_model_skips_json():
    provider = ScriptedProvider(
        [
            [
                {"type": "text_delta", "text": "1. 读取真实持仓\n"},
                {"type": "text_delta", "text": "2. 诊断持仓风险\n"},
                {"type": "text_delta", "text": "3. 形成攻防动作"},
            ]
        ]
    )
    context = route_workflow("用 workflow 做持仓复盘")
    run = plan_workflow("做持仓复盘", context=context, provider=provider, tools=StubToolRegistry())

    assert [step.title for step in run.steps] == ["读取真实持仓", "诊断持仓风险", "形成攻防动作"]
    assert run.script["rationale"] == "planner returned outline text"


def test_tool_descriptions_do_not_use_user_phrase_triggers():
    descriptions = "\n".join(str(schema.get("description") or "") for schema in TOOL_SCHEMAS)

    assert "用户问" not in descriptions
    assert "时调用" not in descriptions


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
