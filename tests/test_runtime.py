from __future__ import annotations

from cli.loop_guard import resolve_turn_expectation
from cli.runtime import AgentRuntime, partition_tool_calls
from cli.workflows.router import WORKFLOWS
from tests.helpers.agent_loop_harness import ScriptedProvider, StubToolRegistry


def test_partition_tool_calls_uses_concurrency_metadata():
    calls = [
        {"id": "tc_a", "name": "fast_a", "args": {}},
        {"id": "tc_b", "name": "fast_b", "args": {}},
        {"id": "tc_c", "name": "write_file", "args": {}},
        {"id": "tc_d", "name": "fast_c", "args": {}},
    ]

    batches = partition_tool_calls(calls, {"fast_a", "fast_b", "fast_c"}.__contains__)

    assert [batch["concurrent"] for batch in batches] == [True, False, True]
    assert [[call["name"] for call in batch["calls"]] for batch in batches] == [
        ["fast_a", "fast_b"],
        ["write_file"],
        ["fast_c"],
    ]


def test_runtime_emits_tool_events_and_done():
    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "view"}}],
                    "text": "",
                },
                {"type": "usage", "input_tokens": 10, "output_tokens": 3},
            ],
            [
                {"type": "text_delta", "text": "你当前没有持仓。"},
                {"type": "usage", "input_tokens": 15, "output_tokens": 8},
            ],
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})
    messages = [{"role": "user", "content": "我的持仓有什么"}]

    events = list(AgentRuntime(provider, tools).run_stream(messages))

    assert [e["type"] for e in events if e["type"].startswith("tool_")] == ["tool_calls", "tool_start", "tool_result"]
    assert events[-1]["type"] == "done"
    assert events[-1]["text"] == "你当前没有持仓。"
    assert events[-1]["usage"] == {"input_tokens": 25, "output_tokens": 11}
    assert any(m.get("role") == "tool" and m.get("name") == "portfolio" for m in messages)


def test_runtime_passes_provider_context_window_to_compaction(monkeypatch):
    captured: dict[str, int | None] = {}

    def fake_compact_messages(messages, provider, model_name="", context_window=None, **_kwargs):
        captured["context_window"] = context_window
        return messages, False, None

    monkeypatch.setattr("cli.runtime.compact_messages", fake_compact_messages)
    provider = ScriptedProvider(rounds=[[{"type": "text_delta", "text": "ok"}]])
    provider.context_window = 123_456

    events = list(AgentRuntime(provider, StubToolRegistry()).run_stream([{"role": "user", "content": "hi"}]))

    assert captured["context_window"] == 123_456
    assert events[-1]["type"] == "done"


def test_runtime_does_not_rewrite_inline_tool_result_between_rounds():
    payload = "x" * 1200

    def second_round(messages, _tools, _system_prompt):
        tool_message = next(m for m in messages if m.get("role") == "tool" and m.get("name") == "portfolio")
        assert payload in tool_message["content"]
        return [{"type": "text_delta", "text": "已基于原始工具结果继续。"}]

    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "view"}}],
                    "text": "",
                }
            ],
            second_round,
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": [], "payload": payload}})
    messages = [{"role": "user", "content": "看一下持仓"}]

    events = list(AgentRuntime(provider, tools).run_stream(messages))

    assert events[-1]["text"] == "已基于原始工具结果继续。"


def test_runtime_emits_retry_event_when_required_tool_is_skipped():
    provider = ScriptedProvider(
        rounds=[
            [
                {"type": "text_delta", "text": "我先说下计划。"},
                {"type": "usage", "input_tokens": 5, "output_tokens": 4},
            ],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_diag", "name": "portfolio", "args": {"mode": "diagnose"}}],
                    "text": "",
                },
                {"type": "usage", "input_tokens": 8, "output_tokens": 3},
            ],
            [
                {"type": "text_delta", "text": "体检完成。"},
                {"type": "usage", "input_tokens": 12, "output_tokens": 5},
            ],
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})
    messages = [
        {"role": "user", "content": "我的持仓有什么"},
        {"role": "assistant", "content": "你手里现在有 4 张牌。"},
        {"role": "user", "content": "做一下体检"},
    ]

    events = list(AgentRuntime(provider, tools, enforce_turn_expectations=True).run_stream(messages))

    retries = [e for e in events if e["type"] == "retry"]
    assert len(retries) == 1
    assert retries[0]["required_tool"] == "portfolio"
    assert '建议参数：mode="diagnose"' in retries[0]["message"]
    assert "不要重复计划" in retries[0]["message"]
    assert events[-1]["text"] == "体检完成。"


def test_runtime_accepts_any_portfolio_mode_for_soft_expectation():
    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "view"}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "已读取持仓。"}],
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})
    messages = [{"role": "user", "content": "账户里这些仓位有什么风险"}]

    events = list(AgentRuntime(provider, tools, enforce_turn_expectations=True).run_stream(messages))

    assert not [e for e in events if e["type"] == "retry"]
    assert events[-1]["text"] == "已读取持仓。"


def test_turn_expectation_requires_portfolio_for_read_positions_wording():
    expectation = resolve_turn_expectation([{"role": "user", "content": "读取真实持仓"}])

    assert expectation is not None
    assert expectation.required_tool == "portfolio"
    assert expectation.suggested_args == {"mode": "view"}


def test_runtime_blocks_question_before_required_portfolio_tool():
    def _portfolio_round(messages, _tools, _system_prompt):
        ask_result = next(m for m in messages if m.get("role") == "tool" and m.get("name") == "ask_user_question")
        assert "先不要向用户提问" in ask_result["content"]
        assert "portfolio" in ask_result["content"]
        return [
            {
                "type": "tool_calls",
                "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "view"}}],
                "text": "",
            }
        ]

    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "tc_ask",
                            "name": "ask_user_question",
                            "args": {"question": "你现在有持仓吗？"},
                        }
                    ],
                    "text": "",
                }
            ],
            _portfolio_round,
            [{"type": "text_delta", "text": "已读取持仓。"}],
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})
    messages = [{"role": "user", "content": "你看我持仓呀"}]

    events = list(AgentRuntime(provider, tools, enforce_turn_expectations=True).run_stream(messages))

    ask_errors = [event for event in events if event["type"] == "tool_error" and event["name"] == "ask_user_question"]
    assert len(ask_errors) == 1
    assert "先不要向用户提问" in ask_errors[0]["error"]
    assert not [event for event in events if event["type"] == "tool_start" and event["name"] == "ask_user_question"]
    assert [call["name"] for call in tools.calls] == ["portfolio"]
    assert events[-1]["text"] == "已读取持仓。"


def test_runtime_leaves_portfolio_typo_diagnosis_to_model_semantics():
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "我先按最可能语义处理，并说明假设。"}],
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})
    messages = [{"role": "user", "content": "给我做磁场诊断"}]

    events = list(AgentRuntime(provider, tools, enforce_turn_expectations=True).run_stream(messages))

    retries = [event for event in events if event["type"] == "retry"]
    assert retries == []
    assert tools.calls == []
    assert events[-1]["text"] == "我先按最可能语义处理，并说明假设。"


def test_runtime_retries_when_stock_screening_request_skips_tool():
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "我先给你讲一下选股框架。"}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_screen", "name": "screen_stocks", "args": {"board": "chinext"}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "创业板候选已筛出。"}],
        ]
    )
    tools = StubToolRegistry(tool_results={"screen_stocks": {"symbols_for_report": ["300750"]}})
    messages = [{"role": "user", "content": "帮我筛选创业板今天有什么好股票"}]

    events = list(AgentRuntime(provider, tools, enforce_turn_expectations=True).run_stream(messages))

    retries = [e for e in events if e["type"] == "retry"]
    assert len(retries) == 1
    assert retries[0]["required_tool"] == "screen_stocks"
    assert '建议参数：board="chinext"' in retries[0]["message"]
    assert events[-1]["text"] == "创业板候选已筛出。"


def test_runtime_retries_when_chatty_watchlist_request_skips_screen_tool():
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "我先说一下筛选思路。"}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_screen", "name": "screen_stocks", "args": {"board": "all"}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "候选和理由已生成。"}],
        ]
    )
    tools = StubToolRegistry(tool_results={"screen_stocks": {"symbols_for_report": ["300750"]}})
    messages = [{"role": "user", "content": "给我找几只值得复核的票，带理由"}]

    events = list(AgentRuntime(provider, tools, enforce_turn_expectations=True).run_stream(messages))

    retries = [event for event in events if event["type"] == "retry"]
    assert len(retries) == 1
    assert retries[0]["required_tool"] == "screen_stocks"
    assert '建议参数：board="all"' in retries[0]["message"]
    assert events[-1]["text"] == "候选和理由已生成。"


def test_runtime_retries_strategy_when_attack_plan_stops_after_screen():
    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_screen", "name": "screen_stocks", "args": {"board": "all"}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "候选已出，风险边界我先口头整理。"}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_strategy", "name": "generate_strategy_decision", "args": {}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "攻防计划已基于工具结果生成。"}],
        ]
    )
    tools = StubToolRegistry(
        tool_results={
            "screen_stocks": {"symbols_for_report": ["300750"]},
            "generate_strategy_decision": {"status": "skipped_notify_unconfigured", "reviewed_codes": ["300750"]},
        }
    )
    messages = [{"role": "user", "content": "给我找几只值得复核的票，带理由和风险边界"}]

    events = list(AgentRuntime(provider, tools, enforce_turn_expectations=True).run_stream(messages))

    retries = [event for event in events if event["type"] == "retry"]
    assert len(retries) == 1
    assert retries[0]["required_tool"] == "generate_strategy_decision"
    assert [call["name"] for call in tools.calls] == ["screen_stocks", "generate_strategy_decision"]
    assert events[-1]["text"] == "攻防计划已基于工具结果生成。"


def test_runtime_retries_when_ai_report_followup_skips_tool():
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "我先整理研报计划。"}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_report", "name": "generate_ai_report", "args": {}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "研报完成。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "generate_ai_report", "description": "r", "parameters": {"type": "object", "properties": {}}},
        ],
        tool_results={"generate_ai_report": {"reviewed_codes": ["300750"]}},
    )
    messages = [
        {
            "role": "assistant",
            "content": (
                "筛选完成。selection_brief status=ready_for_ai_review "
                "tool_handoff=generate_ai_report symbols_for_report=300750"
            ),
        },
        {"role": "user", "content": "继续生成研报"},
    ]

    events = list(AgentRuntime(provider, tools, enforce_turn_expectations=True).run_stream(messages))

    retries = [e for e in events if e["type"] == "retry"]
    assert len(retries) == 1
    assert retries[0]["required_tool"] == "generate_ai_report"
    assert events[-1]["text"] == "研报完成。"


def test_runtime_does_not_retry_stock_screening_explanation_question():
    provider = ScriptedProvider([[{"type": "text_delta", "text": "这套选股逻辑先看阶段、量价和市场门控。"}]])
    tools = StubToolRegistry(tool_results={"screen_stocks": {"symbols_for_report": ["300750"]}})
    messages = [{"role": "user", "content": "讲讲你的选股逻辑是什么"}]

    events = list(AgentRuntime(provider, tools).run_stream(messages))

    assert not [e for e in events if e["type"] == "retry"]
    assert tools.calls == []
    assert events[-1]["text"] == "这套选股逻辑先看阶段、量价和市场门控。"


def test_turn_expectation_does_not_force_tool_for_concept_questions():
    assert resolve_turn_expectation([{"role": "user", "content": "选股规则是什么"}]) is None
    assert resolve_turn_expectation([{"role": "user", "content": "持仓管理是什么"}]) is None
    assert resolve_turn_expectation([{"role": "user", "content": "机会是什么意思"}]) is None


def test_turn_expectation_requires_ai_report_after_screen_handoff():
    expectation = resolve_turn_expectation(
        [
            {
                "role": "assistant",
                "content": (
                    "筛选完成。selection_brief status=ready_for_ai_review "
                    "tool_handoff=generate_ai_report symbols_for_report=300750"
                ),
            },
            {"role": "user", "content": "继续生成研报"},
        ]
    )

    assert expectation is not None
    assert expectation.required_tool == "generate_ai_report"
    assert expectation.suggested_args == {}


def test_turn_expectation_requires_direct_ai_report_task():
    expectation = resolve_turn_expectation([{"role": "user", "content": "生成研报"}])

    assert expectation is not None
    assert expectation.required_tool == "generate_ai_report"


def test_turn_expectation_does_not_force_ai_report_for_vague_review_without_context():
    expectation = resolve_turn_expectation([{"role": "user", "content": "继续复核"}])

    assert expectation is None


def test_turn_expectation_does_not_force_ai_report_for_concept_question():
    expectation = resolve_turn_expectation(
        [
            {
                "role": "assistant",
                "content": (
                    "筛选完成。selection_brief status=ready_for_ai_review "
                    "tool_handoff=generate_ai_report symbols_for_report=300750"
                ),
            },
            {"role": "user", "content": "研报是什么"},
        ]
    )

    assert expectation is None


def test_turn_expectation_still_forces_tool_for_concrete_concept_wording():
    screen = resolve_turn_expectation([{"role": "user", "content": "今天怎么选创业板好股票"}])
    opportunity = resolve_turn_expectation([{"role": "user", "content": "今天有什么机会"}])
    portfolio = resolve_turn_expectation([{"role": "user", "content": "解释一下我的持仓风险"}])

    assert screen is not None
    assert screen.required_tool == "screen_stocks"
    assert screen.suggested_args == {"board": "chinext"}
    assert opportunity is not None
    assert opportunity.required_tool == "screen_stocks"
    assert opportunity.suggested_args == {"board": "all"}
    assert portfolio is not None
    assert portfolio.required_tool == "portfolio"
    assert portfolio.suggested_args == {"mode": "diagnose"}


def test_turn_expectation_does_not_screen_past_recommendation_review():
    expectation = resolve_turn_expectation([{"role": "user", "content": "过去推荐的表现怎么样"}])

    assert expectation is None


def test_turn_expectation_requires_strategy_without_rescreening_existing_candidates():
    expectation = resolve_turn_expectation([{"role": "user", "content": "基于候选 A 制定攻防计划"}])

    assert expectation is not None
    assert expectation.required_tool == "generate_strategy_decision"


def test_turn_expectation_ignores_background_system_notification():
    expectation = resolve_turn_expectation(
        [
            {"role": "user", "content": "帮我筛选创业板今天有什么好股票"},
            {
                "role": "user",
                "content": "[SYSTEM NOTIFICATION - NOT USER INPUT]\n后台筛选完成，候选 300750。",
                "_system_notification": True,
            },
        ]
    )

    assert expectation is None


def test_runtime_answers_all_tool_calls_when_doom_loop_aborts_round():
    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc1", "name": "analyze_stock", "args": {"code": "000001"}}],
                    "text": "",
                }
            ],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc2", "name": "analyze_stock", "args": {"code": "000001"}}],
                    "text": "",
                }
            ],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [
                        {"id": "tc3", "name": "analyze_stock", "args": {"code": "000001"}},
                        {"id": "tc4", "name": "portfolio", "args": {"mode": "view"}},
                    ],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "已中止。"}],
        ]
    )
    tools = StubToolRegistry(
        tool_results={
            "analyze_stock": {"price": 10.5},
            "portfolio": {"positions": []},
        }
    )
    messages = [{"role": "user", "content": "反复查 000001 后再取附加数据"}]

    events = list(AgentRuntime(provider, tools).run_stream(messages))

    third_assistant = [m for m in messages if m.get("role") == "assistant" and len(m.get("tool_calls", [])) == 2][0]
    tool_call_ids = {call["id"] for call in third_assistant["tool_calls"]}
    answered_ids = {
        m["tool_call_id"] for m in messages if m.get("role") == "tool" and m.get("tool_call_id") in tool_call_ids
    }
    assert answered_ids == tool_call_ids
    assert any(e["type"] == "tool_error" and e["tool_call_id"] == "tc4" for e in events)


def test_runtime_filters_tools_for_workflow_scope():
    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "diagnose"}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "ok"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "portfolio", "description": "p", "parameters": {"type": "object", "properties": {}}},
            {"name": "run_backtest", "description": "b", "parameters": {"type": "object", "properties": {}}},
            {
                "name": "ask_user_question",
                "description": "q",
                "parameters": {"type": "object", "properties": {}},
            },
        ]
    )

    events = list(
        AgentRuntime(provider, tools, workflow=WORKFLOWS["portfolio_review"]).run_stream(
            [{"role": "user", "content": "我的持仓怎么样"}]
        )
    )

    exposed = {schema["name"] for schema in provider.calls[0]["tools"]}
    assert "portfolio" in exposed
    assert "ask_user_question" in exposed
    assert "run_backtest" not in exposed
    assert events[0]["type"] == "workflow_start"
    assert events[0]["workflow"] == "portfolio_review"


def test_runtime_blocks_tool_outside_workflow_scope():
    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_bt", "name": "run_backtest", "args": {}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "已拒绝越权工具。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "portfolio", "description": "p", "parameters": {"type": "object", "properties": {}}},
            {"name": "run_backtest", "description": "b", "parameters": {"type": "object", "properties": {}}},
        ]
    )

    events = list(
        AgentRuntime(provider, tools, workflow=WORKFLOWS["portfolio_review"]).run_stream(
            [{"role": "user", "content": "帮我跑回测"}]
        )
    )

    assert tools.calls == []
    assert any(e["type"] == "tool_error" and "workflow" in e["error"] for e in events)
