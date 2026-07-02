from __future__ import annotations

import json

from cli.__main__ import _workflow_script_cli_line, _workflow_step_cli_line
from cli.runtime import AgentRuntime
from cli.tools import TOOL_SCHEMAS
from cli.workflows.dispatch import build_turn_runtime, infer_direct_allowed_tools
from cli.workflows.executor import WorkflowExecutor
from cli.workflows.model_router import _ROUTER_SYSTEM_PROMPT
from cli.workflows.planner import _PLAN_SYSTEM_PROMPT, _REPAIR_SYSTEM_PROMPT, plan_workflow
from cli.workflows.router import WORKFLOWS, build_workflow_system_prompt, route_workflow
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
            "rationale": "先确认真实仓位",
            "success_criteria": "输出风险摘要",
            "risk_guard": "不写入交易",
            "summary": "analysis: completed",
        }
    )

    assert "[completed] 读取持仓" in line
    assert "analysis tools=portfolio,analyze_stock" in line
    assert "goal=先确认真实仓位" in line
    assert "done=输出风险摘要" in line
    assert "guard=不写入交易" in line
    assert "analysis: completed" in line


def test_workflow_step_cli_line_includes_effective_tool_scope():
    line = _workflow_step_cli_line(
        {
            "status": "running",
            "title": "复盘持仓",
            "agent": "task",
            "tool_scope": [],
            "effective_tool_scope": ["portfolio", "analyze_stock"],
        }
    )

    assert "[running] 复盘持仓" in line
    assert "optional_tools=portfolio,analyze_stock" in line


def test_workflow_script_cli_line_surfaces_model_contract_repair():
    line = _workflow_script_cli_line(
        {
            "script": {
                "runtime": {
                    "planner": "model_script",
                    "tool_contract_repair": "model",
                    "unscoped_step_count_before_repair": 2,
                }
            }
        }
    )

    assert "source=model_script" in line
    assert "tool_contract_repair=model:2" in line


def test_workflow_script_cli_line_labels_stock_selection_fallback():
    line = _workflow_script_cli_line(
        {
            "script": {
                "runtime": {
                    "planner": "fallback_script",
                    "fallback_kind": "stock_selection",
                    "fallback_reason": "provider unavailable",
                }
            }
        }
    )

    assert "source=stock_selection_fallback" in line
    assert "source=fallback_script" not in line


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
    assert "错别字" in prompt


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


def test_route_workflow_leaves_obvious_stock_selection_to_model_router():
    workflow = route_workflow("帮我完整做一遍今天的A股选股，给出候选、理由和买卖计划")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_leaves_short_stock_selection_delivery_to_model_router():
    workflow = route_workflow("帮我选出好股票")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_leaves_colloquial_good_stock_request_to_model_router():
    workflow = route_workflow("给我找几个好票，带理由和攻防计划")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_leaves_colloquial_good_target_request_to_model_router():
    workflow = route_workflow("帮我找好标的")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_leaves_chatty_stock_opportunity_request_to_model_router():
    workflow = route_workflow("今天A股有什么机会，给我候选和风险边界")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_leaves_chatty_watchlist_request_to_model_router():
    workflow = route_workflow("给我找几只值得复核的票，带理由和攻防计划")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_keeps_simple_stock_selection_concept_direct():
    workflow = route_workflow("好股票是什么意思？")

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "普通工具型对话交给直接 agent"
    assert workflow.route_matches == ()


def test_route_workflow_keeps_stock_selection_how_to_direct():
    workflow = route_workflow("怎么选出好股票？")

    assert workflow.name == "general_chat"
    assert workflow.route_matches == ()


def test_route_workflow_keeps_good_stock_term_question_direct():
    workflow = route_workflow("好票是什么意思？")

    assert workflow.name == "general_chat"
    assert workflow.route_matches == ()


def test_route_workflow_keeps_good_target_term_question_direct():
    workflow = route_workflow("好标的是什么意思？")

    assert workflow.name == "general_chat"
    assert workflow.route_matches == ()


def test_route_workflow_keeps_stock_selection_method_question_direct():
    workflow = route_workflow("怎么找值得跟踪的票？")

    assert workflow.name == "general_chat"
    assert workflow.route_matches == ()


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


def test_dispatch_direct_runtime_enforces_tool_expectations_by_default():
    provider = ScriptedProvider(
        [
            [{"type": "text_delta", "text": "计划\n1. 读取持仓\n2. 汇总风险"}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "view"}}],
                }
            ],
            [{"type": "text_delta", "text": "已读取持仓。"}],
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})
    runtime, workflow = build_turn_runtime(provider, tools, session_id="s1", user_text="你看我持仓呀")

    events = list(runtime.run_stream([{"role": "user", "content": "你看我持仓呀"}]))

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)
    assert [call["name"] for call in tools.calls] == ["portfolio"]
    assert [event["type"] for event in events].count("retry") == 1
    assert events[-1]["text"] == "已读取持仓。"


def test_dispatch_can_disable_direct_runtime_tool_expectations():
    provider = ScriptedProvider([[{"type": "text_delta", "text": "计划\n1. 读取持仓\n2. 汇总风险"}]])
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})
    runtime, workflow = build_turn_runtime(
        provider,
        tools,
        session_id="s1",
        user_text="你看我持仓呀",
        enforce_turn_expectations=False,
    )

    events = list(runtime.run_stream([{"role": "user", "content": "你看我持仓呀"}]))

    assert workflow.name == "general_chat"
    assert tools.calls == []
    assert not [event for event in events if event["type"] == "retry"]
    assert events[-1]["text"] == "计划\n1. 读取持仓\n2. 汇总风险"


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


def test_dispatch_passes_recent_dialogue_to_model_router():
    provider = RouterDecisionProvider(
        '{"mode":"dynamic_workflow","confidence":0.86,"reason":"承接上一轮候选继续做攻防计划"}'
    )
    messages = [
        {"role": "user", "content": "帮我找几只值得复核的票"},
        {"role": "assistant", "content": "候选：300750 宁德时代、002475 立讯精密。"},
        {"role": "user", "content": "再带上风险边界和买卖计划"},
    ]

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="再带上风险边界和买卖计划",
        routing_messages=messages,
    )

    prompt = provider.chat_calls[0]["messages"][0]["content"]
    assert isinstance(runtime, WorkflowExecutor)
    assert workflow.name == "dynamic_task"
    assert "最近对话" in prompt
    assert "候选：300750 宁德时代" in prompt
    assert "再带上风险边界和买卖计划" in prompt


def test_dispatch_router_uses_raw_current_user_text_when_memory_is_prepended():
    provider = RouterDecisionProvider('{"mode":"direct","confidence":0.9,"reason":"单轮问题"}')
    messages = [
        {
            "role": "user",
            "content": "memory\n- 过去偏好...\n\n<user-request>\n解释一下攻防计划\n</user-request>",
            "_raw_content": "解释一下攻防计划",
        }
    ]

    build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="解释一下攻防计划",
        routing_messages=messages,
    )

    prompt = provider.chat_calls[0]["messages"][0]["content"]
    assert "用户请求:\n解释一下攻防计划" in prompt
    assert "memory" not in prompt


def test_model_router_prompt_is_minimal_runtime_contract():
    assert "默认用 direct" in _ROUTER_SYSTEM_PROMPT
    assert "dynamic_workflow" in _ROUTER_SYSTEM_PROMPT
    assert "不改写" in _ROUTER_SYSTEM_PROMPT
    assert "语义判断" in _ROUTER_SYSTEM_PROMPT
    assert "错别字" in _ROUTER_SYSTEM_PROMPT
    assert "逐字匹配" in _ROUTER_SYSTEM_PROMPT
    assert "候选池" in _ROUTER_SYSTEM_PROMPT
    assert "风险边界" in _ROUTER_SYSTEM_PROMPT
    assert "行动计划" in _ROUTER_SYSTEM_PROMPT
    assert "不需要可见进度" in _ROUTER_SYSTEM_PROMPT
    assert "一个清楚目标" not in _ROUTER_SYSTEM_PROMPT
    assert "用户表达不标准" not in _ROUTER_SYSTEM_PROMPT
    assert "语义恢复" not in _ROUTER_SYSTEM_PROMPT
    assert "措辞恢复" not in _ROUTER_SYSTEM_PROMPT
    assert "谐音" not in _ROUTER_SYSTEM_PROMPT
    assert "查看持仓" not in _ROUTER_SYSTEM_PROMPT
    assert "单只股票诊断" not in _ROUTER_SYSTEM_PROMPT


def test_planner_prompt_preserves_multi_candidate_delivery_contract():
    assert "找几个/几只/一些候选" in _PLAN_SYSTEM_PROMPT
    assert "保留候选名称、理由、风险边界和下一步动作" in _PLAN_SYSTEM_PROMPT
    assert "错别字" in _PLAN_SYSTEM_PROMPT


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


def test_dispatch_accepts_nested_router_decision_payload():
    provider = RouterDecisionProvider(
        '{"runtime":{"latency_ms":12},"routing":{"execution":"plan","reason":"需要先看市场再筛候选"},"confidence":0.86}'
    )

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="今天帮我找几个有攻防空间的机会",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_confidence == 0.86
    assert workflow.route_reason == "模型判断需要动态 workflow：需要先看市场再筛候选"
    assert isinstance(runtime, WorkflowExecutor)


def test_dispatch_preserves_reason_from_nested_route_mode_payload():
    provider = RouterDecisionProvider(
        '{"route":{"mode":"dynamic_workflow","confidence":0.87,"reason":"需要先筛候选再给攻防"}}'
    )

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="今天找几个好票带攻防",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_confidence == 0.87
    assert workflow.route_reason == "模型判断需要动态 workflow：需要先筛候选再给攻防"
    assert isinstance(runtime, WorkflowExecutor)


def test_dispatch_keeps_top_level_router_mode_over_nested_metadata():
    provider = RouterDecisionProvider(
        '{"mode":"direct","reason":"单轮解释","route":{"mode":"dynamic_workflow","reason":"嵌套调试信息"}}'
    )

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="解释一下 workflow 是什么",
    )

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "模型判断直接处理：单轮解释"
    assert isinstance(runtime, AgentRuntime)


def test_dispatch_accepts_planning_flag_without_mode():
    provider = RouterDecisionProvider('{"needs_plan":true,"score":"71%","reason":"需要跨候选复核"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="把今天值得看的方向分层复核一下",
    )

    assert workflow.name == "dynamic_task"
    assert workflow.route_confidence == 0.71
    assert workflow.route_reason == "模型判断需要动态 workflow：需要跨候选复核"
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


def test_dispatch_respects_direct_model_route_for_stock_selection_delivery():
    provider = RouterDecisionProvider('{"mode":"direct","confidence":0.91,"reason":"用户只是要几个股票名字"}')

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我选出好股票",
    )

    assert workflow.name == "general_chat"
    assert workflow.route_reason == "模型判断直接处理：用户只是要几个股票名字"
    assert workflow.route_confidence == 0.91
    assert workflow.route_matches == ("model_router",)
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


def test_dispatch_falls_back_to_workflow_for_stock_selection_when_model_router_is_unavailable():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我完整做一遍今天的A股选股，给出候选、理由和买卖计划",
    )

    assert workflow.name == "dynamic_task"
    assert isinstance(runtime, WorkflowExecutor)
    assert workflow.route_reason == "模型路由不可用（无路由响应），核心选股请求兜底进入动态 workflow"
    assert workflow.route_matches == ("model_router_fallback", "stock_selection_guard")


def test_dispatch_falls_back_to_workflow_for_short_stock_selection_when_model_router_is_unavailable():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我选出好股票",
    )

    assert workflow.name == "dynamic_task"
    assert isinstance(runtime, WorkflowExecutor)
    assert workflow.route_reason == "模型路由不可用（无路由响应），核心选股请求兜底进入动态 workflow"
    assert workflow.route_matches == ("model_router_fallback", "stock_selection_guard")


def test_dispatch_falls_back_to_workflow_for_chatty_stock_selection_when_model_router_is_unavailable():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="今天A股有什么机会，给我候选和风险边界",
    )

    assert workflow.name == "dynamic_task"
    assert isinstance(runtime, WorkflowExecutor)
    assert workflow.route_reason == "模型路由不可用（无路由响应），核心选股请求兜底进入动态 workflow"
    assert workflow.route_matches == ("model_router_fallback", "stock_selection_guard")


def test_dispatch_surfaces_invalid_model_router_json():
    provider = RouterDecisionProvider("这不是 JSON")

    runtime, workflow = build_turn_runtime(
        provider,
        StubToolRegistry(),
        session_id="s1",
        user_text="帮我完整做一遍今天的A股选股，给出候选、理由和买卖计划",
    )

    assert workflow.name == "dynamic_task"
    assert isinstance(runtime, WorkflowExecutor)
    assert workflow.route_reason == "模型路由不可用（路由 JSON 无效），核心选股请求兜底进入动态 workflow"
    assert workflow.route_matches == ("model_router_fallback", "stock_selection_guard")


def test_dispatch_keeps_stock_selection_method_question_direct_when_model_router_is_unavailable():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="怎么选出好股票？",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)
    assert workflow.route_reason == "模型路由不可用（无路由响应），直接 agent 处理"
    assert workflow.route_matches == ("model_router_fallback",)


def test_dispatch_keeps_non_stock_opportunity_question_direct_when_model_router_is_unavailable():
    runtime, workflow = build_turn_runtime(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s1",
        user_text="这个项目有什么机会和风险",
    )

    assert workflow.name == "general_chat"
    assert isinstance(runtime, AgentRuntime)
    assert workflow.route_reason == "模型路由不可用（无路由响应），直接 agent 处理"
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
    assert "错别字" in prompt
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
    assert "evaluate_recommendation_events" in runtime.allowed_tools
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
    assert "evaluate_recommendation_events" in tools
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


def test_planner_accepts_tool_display_names_from_model_script():
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
    assert run.steps[0].tool_scope == ("portfolio", "screen_stocks")


def test_planner_keeps_question_tool_for_clarification_only_task():
    context = route_workflow("用 workflow 问清楚回测范围")
    run = plan_workflow(
        "问清楚回测范围",
        context=context,
        workflow_script={
            "tasks": [
                {
                    "id": "clarify",
                    "title": "确认回测范围",
                    "tools": ["ask_user_question"],
                    "prompt": "只有用户未给出必要范围时，询问回测区间。",
                }
            ]
        },
    )

    assert run.steps[0].tool_scope == ("ask_user_question",)


def test_planner_does_not_infer_tools_from_json_task_text_when_model_omits_tools():
    provider = ScriptedProvider(
        [
            [
                {
                    "type": "text_delta",
                    "text": (
                        '{"title":"自然工具推断","phases":[{"tasks":['
                        '{"id":"positions","title":"读取真实持仓","prompt":"诊断持仓风险并输出当前仓位摘要。"},'
                        '{"id":"scan","title":"扫描今日机会池","prompt":"筛选候选股票并保留候选理由。"},'
                        '{"id":"plan","title":"输出触发位和失效位",'
                        '"prompt":"形成候选攻防计划，给出入场位、止损位和风险边界。"}'
                        "]}]}"
                    ),
                }
            ]
        ]
    )
    context = route_workflow("用 workflow 做持仓和选股复盘")
    run = plan_workflow(
        "做持仓和选股复盘",
        context=context,
        provider=provider,
        tools=StubToolRegistry(),
    )

    assert [step.tool_scope for step in run.steps] == [(), (), ()]


def test_planner_lets_model_repair_missing_tool_contracts():
    first_script = {
        "title": "动态选股",
        "phases": [
            {
                "id": "select",
                "tasks": [
                    {"id": "scan", "title": "扫描候选", "prompt": "筛选今日候选并保留理由。"},
                    {
                        "id": "decision",
                        "title": "形成攻防",
                        "depends_on": ["scan"],
                        "prompt": "基于候选输出触发位、失效位和风险边界。",
                    },
                ],
            }
        ],
    }
    repaired_script = {
        "title": "动态选股",
        "phases": [
            {
                "id": "select",
                "tasks": [
                    {
                        "id": "scan",
                        "title": "扫描候选",
                        "tools": ["screen_stocks"],
                        "prompt": "筛选今日候选并保留理由。",
                    },
                    {
                        "id": "decision",
                        "title": "形成攻防",
                        "tools": ["generate_strategy_decision"],
                        "depends_on": ["scan"],
                        "prompt": "基于候选输出触发位、失效位和风险边界。",
                    },
                ],
            }
        ],
    }
    provider = ScriptedProvider(
        [
            [{"type": "text_delta", "text": json.dumps(first_script, ensure_ascii=False)}],
            [{"type": "text_delta", "text": json.dumps(repaired_script, ensure_ascii=False)}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "screen_stocks"},
            {"name": "generate_strategy_decision"},
        ]
    )

    run = plan_workflow(
        "用 workflow 选出好股票并给出攻防计划",
        context=route_workflow("用 workflow 选出好股票并给出攻防计划"),
        provider=provider,
        tools=tools,
    )

    assert [step.tool_scope for step in run.steps] == [("screen_stocks",), ("generate_strategy_decision",)]
    assert run.steps[1].depends_on == ("scan",)
    assert run.script["runtime"]["tool_contract_repair"] == "model"
    assert run.script["runtime"]["unscoped_step_count_before_repair"] == 2
    assert provider.calls[1]["system_prompt"] == _REPAIR_SYSTEM_PROMPT
    assert "- screen_stocks" in provider.calls[1]["messages"][0]["content"]


def test_planner_keeps_original_script_when_model_tool_contract_repair_is_invalid():
    provider = ScriptedProvider(
        [
            [
                {
                    "type": "text_delta",
                    "text": '{"title":"自然工具推断","tasks":[{"id":"scan","title":"扫描候选","prompt":"筛选候选。"}]}',
                }
            ],
            [{"type": "text_delta", "text": "这不是 JSON"}],
        ]
    )
    tools = StubToolRegistry(schemas=[{"name": "screen_stocks"}])

    run = plan_workflow(
        "用 workflow 找好票",
        context=route_workflow("用 workflow 找好票"),
        provider=provider,
        tools=tools,
    )

    assert run.script["title"] == "自然工具推断"
    assert run.steps[0].tool_scope == ()
    assert "tool_contract_repair" not in run.script["runtime"]


def test_planner_filters_model_task_tools_by_workflow_context():
    provider = ScriptedProvider(
        [
            [
                {
                    "type": "text_delta",
                    "text": (
                        '{"title":"历史选股上下文","phases":[{"tasks":['
                        '{"id":"scan","title":"扫描候选","tools":["screen_stocks","generate_strategy_decision"],'
                        '"prompt":"扫描候选并形成攻防计划。"},'
                        '{"id":"levels","title":"输出触发位和失效位",'
                        '"prompt":"给出触发位、失效位和风险边界。"}'
                        "]}]}"
                    ),
                }
            ]
        ]
    )
    run = plan_workflow(
        "继续选股扫描",
        context=WORKFLOWS["stock_screen"],
        provider=provider,
        tools=StubToolRegistry(),
    )

    assert [step.tool_scope for step in run.steps] == [("screen_stocks",), ()]


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


def test_planner_accepts_common_tool_scope_variants_from_model_script():
    context = route_workflow("用 workflow 做选股和攻防计划")
    run = plan_workflow(
        "做选股和攻防计划",
        context=context,
        workflow_script={
            "tasks": [
                {
                    "id": "scan",
                    "title": "扫描候选",
                    "required_tools": ["调用 screen_stocks", "大盘水温"],
                    "prompt": "扫描候选并读取市场环境。",
                },
                {
                    "id": "report",
                    "title": "生成研报",
                    "tool_names": "深度审讯",
                    "after": "scan",
                    "prompt": "基于候选生成研报。",
                },
                {
                    "id": "decision",
                    "title": "形成攻防",
                    "tool_calls": [{"function": {"name": "generate_strategy_decision"}}],
                    "after": "report",
                    "prompt": "输出候选攻防计划。",
                },
            ]
        },
    )

    assert [step.tool_scope for step in run.steps] == [
        ("screen_stocks", "get_market_overview"),
        ("generate_ai_report",),
        ("generate_strategy_decision",),
    ]


def test_planner_flattens_nested_tool_scope_wrappers_from_model_script():
    context = route_workflow("用 workflow 做选股和攻防计划")
    run = plan_workflow(
        "做选股和攻防计划",
        context=context,
        workflow_script={
            "tasks": [
                {
                    "id": "scan",
                    "title": "扫描候选",
                    "tool_scope": {"required": ["screen_stocks", "get_market_overview"]},
                    "prompt": "扫描候选并读取市场水温。",
                },
                {
                    "id": "report",
                    "title": "生成研报",
                    "tool_uses": [{"type": "tool_use", "name": "generate_ai_report"}],
                    "prompt": "基于候选生成研报。",
                },
                {
                    "id": "decision",
                    "title": "形成攻防",
                    "function_calls": [{"function": {"name": "generate_strategy_decision"}}],
                    "prompt": "输出候选攻防计划。",
                },
            ]
        },
    )

    assert [step.tool_scope for step in run.steps] == [
        ("screen_stocks", "get_market_overview"),
        ("generate_ai_report",),
        ("generate_strategy_decision",),
    ]


def test_planner_stabilizes_missing_stock_selection_dependencies():
    context = route_workflow("用 workflow 做选股、研报和攻防计划")
    run = plan_workflow(
        "做选股、研报和攻防计划",
        context=context,
        workflow_script={
            "tasks": [
                {"id": "scan", "title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描今日候选。"},
                {"id": "report", "title": "生成研报", "tools": ["generate_ai_report"], "prompt": "基于候选生成研报。"},
                {
                    "id": "decision",
                    "title": "形成攻防",
                    "tools": ["generate_strategy_decision"],
                    "depends_on": ["market"],
                    "prompt": "基于候选和研报输出攻防边界。",
                },
            ]
        },
    )

    assert [step.step_id for step in run.steps] == ["scan", "report", "decision"]
    assert run.steps[0].depends_on == ()
    assert run.steps[1].depends_on == ("scan",)
    assert run.steps[2].depends_on == ("market", "report")


def test_planner_stabilizes_no_tool_synthesis_after_fact_tasks():
    run = plan_workflow(
        "复盘我的持仓，结合市场给出去留和风险动作",
        context=WORKFLOWS["portfolio_review"],
        workflow_script={
            "tasks": [
                {"id": "positions", "title": "读取持仓", "tools": ["portfolio"], "prompt": "读取当前持仓。"},
                {
                    "id": "market",
                    "title": "读取市场环境",
                    "tools": ["get_market_overview"],
                    "prompt": "读取当前市场水温。",
                },
                {
                    "id": "decision",
                    "title": "形成去留和风险动作",
                    "prompt": "基于持仓和市场环境，输出每个持仓的去留、风险边界和下一步动作。",
                },
            ]
        },
    )

    assert [step.step_id for step in run.steps] == ["positions", "market", "decision"]
    assert run.steps[0].depends_on == ()
    assert run.steps[1].depends_on == ()
    assert run.steps[2].depends_on == ("positions", "market")


def test_planner_synthesis_ignores_unrelated_following_fact_task():
    run = plan_workflow(
        "复盘我的持仓，结合市场给出去留和风险动作，然后再扫候选",
        context=WORKFLOWS["portfolio_review"],
        workflow_script={
            "tasks": [
                {"id": "positions", "title": "读取持仓", "tools": ["portfolio"], "prompt": "读取当前持仓。"},
                {
                    "id": "market",
                    "title": "读取市场环境",
                    "tools": ["get_market_overview"],
                    "prompt": "读取当前市场水温。",
                },
                {
                    "id": "decision",
                    "title": "形成去留和风险动作",
                    "prompt": "基于持仓和市场环境，输出每个持仓的去留、风险边界和下一步动作。",
                },
                {"id": "scan", "title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描候选股票。"},
            ]
        },
    )

    assert [step.step_id for step in run.steps] == ["positions", "market", "decision", "scan"]
    assert run.steps[2].depends_on == ("positions", "market")
    assert run.steps[3].depends_on == ()


def test_planner_resolves_dependency_titles_to_step_ids():
    context = route_workflow("用 workflow 做选股、研报和攻防计划")
    run = plan_workflow(
        "做选股、研报和攻防计划",
        context=context,
        workflow_script={
            "tasks": [
                {"id": "scan", "title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描今日候选。"},
                {
                    "id": "report",
                    "title": "生成研报",
                    "tools": ["generate_ai_report"],
                    "after": "扫描候选",
                    "prompt": "基于候选生成研报。",
                },
                {
                    "id": "decision",
                    "title": "形成攻防",
                    "tools": ["generate_strategy_decision"],
                    "after": {"title": "生成研报"},
                    "prompt": "基于候选和研报输出攻防边界。",
                },
            ]
        },
    )

    assert run.steps[0].depends_on == ()
    assert run.steps[1].depends_on == ("scan",)
    assert run.steps[2].depends_on == ("report",)


def test_planner_stabilizes_out_of_order_stock_selection_dependencies():
    context = route_workflow("用 workflow 做选股、研报和攻防计划")
    run = plan_workflow(
        "做选股、研报和攻防计划",
        context=context,
        workflow_script={
            "tasks": [
                {
                    "id": "decision",
                    "title": "形成攻防",
                    "tools": ["generate_strategy_decision"],
                    "prompt": "基于候选和研报输出攻防边界。",
                },
                {"id": "report", "title": "生成研报", "tools": ["generate_ai_report"], "prompt": "基于候选生成研报。"},
                {"id": "scan", "title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描今日候选。"},
            ]
        },
    )

    assert [step.step_id for step in run.steps] == ["decision", "report", "scan"]
    assert run.steps[0].depends_on == ("report",)
    assert run.steps[1].depends_on == ("scan",)
    assert run.steps[2].depends_on == ()


def test_planner_stabilizes_cross_phase_stock_selection_dependencies():
    context = route_workflow("用 workflow 做选股、研报和攻防计划")
    run = plan_workflow(
        "做选股、研报和攻防计划",
        context=context,
        workflow_script={
            "phases": [
                {
                    "id": "decision",
                    "tasks": [
                        {
                            "id": "decision",
                            "title": "形成攻防",
                            "tools": ["generate_strategy_decision"],
                            "prompt": "基于候选和研报输出攻防边界。",
                        }
                    ],
                },
                {
                    "id": "report",
                    "tasks": [
                        {
                            "id": "report",
                            "title": "生成研报",
                            "tools": ["generate_ai_report"],
                            "prompt": "基于候选生成研报。",
                        }
                    ],
                },
                {
                    "id": "scan",
                    "tasks": [
                        {"id": "scan", "title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描今日候选。"}
                    ],
                },
            ]
        },
    )

    assert [step.step_id for step in run.steps] == ["decision", "report", "scan"]
    assert run.steps[0].depends_on == ("report",)
    assert run.steps[1].depends_on == ("scan",)
    assert run.steps[2].depends_on == ()


def test_planner_does_not_self_depend_when_task_combines_screen_and_decision_tools():
    context = route_workflow("用 workflow 做选股和攻防计划")
    run = plan_workflow(
        "做选股和攻防计划",
        context=context,
        workflow_script={
            "tasks": [
                {
                    "id": "all_in_one",
                    "title": "扫描并形成攻防",
                    "tools": ["screen_stocks", "generate_strategy_decision"],
                    "prompt": "先筛候选，再在同一 task 内形成攻防计划。",
                }
            ]
        },
    )

    assert run.steps[0].tool_scope == ("screen_stocks", "generate_strategy_decision")
    assert run.steps[0].depends_on == ()


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


def test_planner_unwraps_workflow_container_from_generated_script():
    provider = ScriptedProvider(
        [
            [
                {
                    "type": "text_delta",
                    "text": (
                        '{"workflow":{"title":"选股流程","phases":[{"tasks":['
                        '{"id":"scan","title":"扫描候选","tools":["screen_stocks"],"prompt":"扫描候选"}'
                        "]}]}}"
                    ),
                }
            ]
        ]
    )
    context = route_workflow("用 workflow 选出好股票")
    run = plan_workflow("选出好股票", context=context, provider=provider, tools=StubToolRegistry())

    assert run.script["title"] == "选股流程"
    assert run.script["runtime"]["planner"] == "model_script"
    assert [step.step_id for step in run.steps] == ["scan"]
    assert run.steps[0].tool_scope == ("screen_stocks",)


def test_planner_unwraps_structured_plan_container_from_model_script():
    context = route_workflow("用 workflow 做选股")
    run = plan_workflow(
        "做选股",
        context=context,
        workflow_script={
            "title": "外层标题",
            "plan": {
                "phases": [
                    {
                        "id": "scan_phase",
                        "tasks": [
                            {
                                "id": "scan",
                                "title": "扫描候选",
                                "tools": ["screen_stocks"],
                                "prompt": "扫描候选。",
                            }
                        ],
                    }
                ]
            },
        },
    )

    assert run.script["title"] == "外层标题"
    assert [step.step_id for step in run.steps] == ["scan"]
    assert run.steps[0].phase == "scan_phase"
    assert run.steps[0].tool_scope == ("screen_stocks",)


def test_planner_accepts_stage_phase_alias_from_generated_script():
    provider = ScriptedProvider(
        [
            [
                {
                    "type": "text_delta",
                    "text": (
                        '{"title":"选股流程","stages":[{"id":"screening","title":"筛选阶段","steps":['
                        '{"id":"scan","title":"扫描候选","tools":["screen_stocks"],"prompt":"扫描候选"}'
                        "]}]}"
                    ),
                }
            ]
        ]
    )
    context = route_workflow("用 workflow 选出好股票")
    run = plan_workflow("选出好股票", context=context, provider=provider, tools=StubToolRegistry())

    assert run.script["runtime"]["planner"] == "model_script"
    assert [step.step_id for step in run.steps] == ["scan"]
    assert run.steps[0].phase == "screening"
    assert run.steps[0].tool_scope == ("screen_stocks",)


def test_planner_accepts_keyed_section_phase_alias_from_model_script():
    context = route_workflow("用 workflow 做选股和攻防")
    run = plan_workflow(
        "做选股和攻防",
        context=context,
        workflow_script={
            "sections": {
                "screening": {
                    "title": "筛选阶段",
                    "tasks": [{"id": "scan", "title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描候选。"}],
                },
                "decision": {
                    "title": "攻防阶段",
                    "tasks": [
                        {
                            "id": "attack",
                            "title": "形成攻防",
                            "tools": ["generate_strategy_decision"],
                            "prompt": "输出攻防计划。",
                        }
                    ],
                },
            }
        },
    )

    assert [step.step_id for step in run.steps] == ["scan", "attack"]
    assert [step.phase for step in run.steps] == ["screening", "decision"]
    assert run.steps[0].tool_scope == ("screen_stocks",)
    assert run.steps[1].tool_scope == ("generate_strategy_decision",)
    assert run.steps[1].depends_on == ("scan",)


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


def test_planner_preserves_outline_text_without_inferred_tools_when_model_skips_json():
    provider = ScriptedProvider(
        [
            [
                {"type": "text_delta", "text": "1. 扫描今日候选\n"},
                {"type": "text_delta", "text": "2. 生成研报\n"},
                {"type": "text_delta", "text": "3. 形成攻防动作"},
            ]
        ]
    )
    context = route_workflow("用 workflow 选出好股票，给出研报和攻防计划")
    run = plan_workflow(
        "选出好股票，给出研报和攻防计划",
        context=context,
        provider=provider,
        tools=StubToolRegistry(),
    )

    assert [step.title for step in run.steps] == ["扫描今日候选", "生成研报", "形成攻防动作"]
    assert [step.tool_scope for step in run.steps] == [(), (), ()]
    assert run.steps[0].depends_on == ()
    assert run.steps[1].depends_on == ()
    assert run.steps[2].depends_on == ()


def test_planner_preserves_colloquial_good_stock_outline_without_inferred_tools():
    provider = ScriptedProvider(
        [
            [
                {"type": "text_delta", "text": "1. 找好票\n"},
                {"type": "text_delta", "text": "2. 形成攻防动作"},
            ]
        ]
    )
    context = route_workflow("用 workflow 找好票，给出攻防")
    run = plan_workflow(
        "找好票，给出攻防",
        context=context,
        provider=provider,
        tools=StubToolRegistry(),
    )

    assert [step.tool_scope for step in run.steps] == [(), ()]
    assert run.steps[1].depends_on == ()


def test_planner_preserves_colloquial_good_target_outline_without_inferred_tools():
    provider = ScriptedProvider(
        [
            [
                {"type": "text_delta", "text": "1. 找好标的\n"},
                {"type": "text_delta", "text": "2. 形成攻防动作"},
            ]
        ]
    )
    context = route_workflow("用 workflow 找好标的，给出攻防")
    run = plan_workflow(
        "找好标的，给出攻防",
        context=context,
        provider=provider,
        tools=StubToolRegistry(),
    )

    assert [step.tool_scope for step in run.steps] == [(), ()]
    assert run.steps[1].depends_on == ()


def test_planner_preserves_holding_outline_without_inferred_tools():
    provider = ScriptedProvider(
        [
            [
                {"type": "text_delta", "text": "1. 读取持仓与资金\n"},
                {"type": "text_delta", "text": "2. 诊断持仓与市场环境\n"},
                {"type": "text_delta", "text": "3. 形成去留和风险动作"},
            ]
        ]
    )
    context = route_workflow("用 workflow 你看我持仓呀")
    run = plan_workflow("你看我持仓呀", context=context, provider=provider, tools=StubToolRegistry())

    assert [step.title for step in run.steps] == ["读取持仓与资金", "诊断持仓与市场环境", "形成去留和风险动作"]
    assert [step.tool_scope for step in run.steps] == [(), (), ()]
    assert run.steps[2].depends_on == ()


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
