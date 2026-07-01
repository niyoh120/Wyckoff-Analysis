from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

from cli.workflows.control import WorkflowControl
from cli.workflows.executor import (
    WorkflowExecutor,
    _phase_batches,
    _step_context,
    _synthesis_prompt,
    _workflow_handoff_state,
)
from cli.workflows.models import WorkflowRun, WorkflowStep
from cli.workflows.planner import _PLAN_SYSTEM_PROMPT, plan_workflow
from cli.workflows.resume import build_resume_prompt
from cli.workflows.router import WORKFLOWS, route_workflow
from cli.workflows.store import get_workflow_run, load_workflow_events
from tests.helpers.agent_loop_harness import ScriptedProvider, StubToolRegistry

_PLAN_JSON = """{
  "title": "持仓复盘",
  "rationale": "先让 sub-agent 读取持仓，再汇总风险动作。",
  "phases": [
    {
      "id": "review",
      "title": "持仓检查",
      "tasks": [
        {
          "id": "read_positions",
          "title": "读取并诊断持仓",
          "agent": "analysis",
          "prompt": "读取用户持仓并输出风险摘要",
          "context": "只看核心仓位，不处理现金。"
        }
      ]
    }
  ],
  "synthesis_prompt": "汇总持仓风险和下一步动作。"
}"""

_PARALLEL_PLAN_JSON = """{
  "title": "并发复核",
  "rationale": "同一阶段并发收集两个视角。",
  "phases": [
    {
      "id": "fanout",
      "title": "并发检查",
      "tasks": [
        {
          "id": "research_view",
          "title": "研究视角",
          "agent": "research",
          "prompt": "从市场数据视角复核"
        },
        {
          "id": "analysis_view",
          "title": "结构视角",
          "agent": "analysis",
          "prompt": "从量价结构视角复核"
        }
      ]
    }
  ],
  "synthesis_prompt": "合并两个视角。"
}"""

_DEPENDENT_PLAN_JSON = """{
  "title": "依赖复核",
  "rationale": "同一阶段内按模型声明的 task 依赖分批执行。",
  "phases": [
    {
      "id": "review",
      "title": "复核阶段",
      "tasks": [
        {
          "id": "scan",
          "title": "扫描候选",
          "agent": "research",
          "prompt": "先扫描候选"
        },
        {
          "id": "risk_plan",
          "title": "攻防计划",
          "agent": "trading",
          "depends_on": ["scan"],
          "prompt": "基于扫描结果输出攻防计划"
        }
      ]
    }
  ],
  "synthesis_prompt": "按依赖顺序汇总。"
}"""

_OUT_OF_ORDER_DEPENDENT_PLAN_JSON = """{
  "title": "乱序依赖复核",
  "phases": [
    {
      "id": "review",
      "tasks": [
        {
          "id": "risk_plan",
          "title": "攻防计划",
          "agent": "trading",
          "depends_on": ["scan"],
          "prompt": "基于扫描结果输出攻防计划"
        },
        {
          "id": "scan",
          "title": "扫描候选",
          "agent": "research",
          "prompt": "先扫描候选"
        }
      ]
    }
  ],
  "synthesis_prompt": "按依赖顺序汇总。"
}"""

_EDITED_PLAN_JSON = """{
  "title": "编辑后脚本",
  "rationale": "用户修改了脚本。",
  "phases": [
    {
      "id": "edited",
      "title": "编辑阶段",
      "tasks": [
        {
          "id": "edited_task",
          "title": "编辑任务",
          "agent": "analysis",
          "prompt": "执行编辑后的任务"
        }
      ]
    }
  ],
  "synthesis_prompt": "汇总编辑后的任务。"
}"""

_SCOPED_TOOL_PLAN_JSON = """{
  "title": "收窄工具复核",
  "phases": [
    {
      "id": "review",
      "tasks": [
        {
          "id": "read_positions",
          "title": "只读取持仓",
          "tools": ["portfolio"],
          "prompt": "读取持仓并输出摘要"
        }
      ]
    }
  ],
  "synthesis_prompt": "汇总持仓摘要。"
}"""


class ParallelResultProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.synthesis_prompt = ""
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "ParallelResultProvider"

    def chat_stream(self, messages, _tools, _system_prompt=""):
        content = messages[0]["content"]
        with self._lock:
            self.calls.append(content)
        if content.startswith("请基于以下动态 workflow 执行结果"):
            self.synthesis_prompt = content
            yield {"type": "text_delta", "text": "两个视角已按脚本顺序合并。"}
            return
        if "从市场数据视角复核" in content:
            time.sleep(0.05)
            yield {"type": "text_delta", "text": "研究视角完成。"}
            return
        if "从量价结构视角复核" in content:
            time.sleep(0.01)
            yield {"type": "text_delta", "text": "结构视角完成。"}
            return
        yield {"type": "text_delta", "text": "未知任务。"}


def _reset_local_db(local_db) -> None:
    if local_db._conn is not None:
        local_db._conn.close()
    local_db._conn = None


def test_workflow_planner_prompt_keeps_task_semantics_model_authored():
    assert "自然语言语义、上下文恢复和任务拆分由你完成" in _PLAN_SYSTEM_PROMPT
    assert "合理推断" in _PLAN_SYSTEM_PROMPT
    assert "按最高置信假设生成可执行 task" in _PLAN_SYSTEM_PROMPT
    assert "措辞恢复" not in _PLAN_SYSTEM_PROMPT
    assert "不要单独生成元任务" not in _PLAN_SYSTEM_PROMPT
    assert "错字" not in _PLAN_SYSTEM_PROMPT
    assert "错别字" not in _PLAN_SYSTEM_PROMPT
    assert "不需要选择内部执行角色" in _PLAN_SYSTEM_PROMPT
    assert "不要填写 agent/role" in _PLAN_SYSTEM_PROMPT
    assert "可用 agent" not in _PLAN_SYSTEM_PROMPT
    assert '"agent": "可选，research|analysis|trading"' not in _PLAN_SYSTEM_PROMPT
    assert "rationale" in _PLAN_SYSTEM_PROMPT
    assert "success_criteria" in _PLAN_SYSTEM_PROMPT
    assert "risk_guard" in _PLAN_SYSTEM_PROMPT


def test_model_generated_workflow_ignores_legacy_agent_and_tool_aliases():
    provider = ScriptedProvider(
        [
            [
                {
                    "type": "text_delta",
                    "text": json.dumps(
                        {
                            "title": "今日选股",
                            "phases": [
                                {
                                    "id": "screen",
                                    "tasks": [
                                        {
                                            "id": "scan",
                                            "title": "扫描候选",
                                            "agent": "analysis",
                                            "tools": ["选股", "screen_stocks"],
                                            "prompt": "扫描今日候选并保留风险原因",
                                        }
                                    ],
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        ]
    )

    run = plan_workflow(
        "帮我完整做一遍今天的 A 股选股",
        context=WORKFLOWS["dynamic_task"],
        provider=provider,
        tools=StubToolRegistry(),
    )

    assert run.script["runtime"]["planner"] == "model_script"
    assert run.steps[0].agent == "task"
    assert run.steps[0].tools == ()
    assert run.steps[0].tool_scope == ("screen_stocks",)


def test_workflow_planner_ignores_agent_aliases_and_keeps_steps_field():
    run = plan_workflow(
        "用 workflow 做完整选股和攻防计划",
        context=route_workflow("用 workflow 做完整选股和攻防计划"),
        workflow_script={
            "title": "选股攻防",
            "phases": [
                {
                    "id": "fanout",
                    "steps": [
                        {"id": "scan", "title": "扫描候选", "agent": "研究", "prompt": "筛选候选股票"},
                        {
                            "id": "risk_plan",
                            "title": "攻防计划",
                            "agent": "delegate_to_trading",
                            "dependsOn": [{"id": "scan"}],
                            "instruction": "输出观察、买入和失效条件",
                        },
                    ],
                }
            ],
        },
    )

    assert [step.agent for step in run.steps] == ["task", "task"]
    assert [step.tools for step in run.steps] == [(), ()]
    assert run.steps[1].prompt == "输出观察、买入和失效条件"
    assert run.steps[1].depends_on == ("scan",)
    assert run.script["runtime"]["planner"] == "stored_script"


def test_workflow_planner_preserves_task_outcome_metadata():
    run = plan_workflow(
        "用 workflow 做今日选股",
        context=route_workflow("用 workflow 做今日选股"),
        workflow_script={
            "title": "带边界的脚本",
            "tasks": [
                {
                    "id": "scan",
                    "title": "扫描候选",
                    "tools": ["screen_stocks"],
                    "prompt": "扫描今日候选并输出风险状态",
                    "why": "先缩小候选池，再决定是否需要研报",
                    "done_when": ["返回候选代码", "说明不能直接买入的边界"],
                    "guardrails": {"write": "不写入推荐或持仓"},
                }
            ],
        },
    )

    step = run.steps[0]
    payload = step.to_dict()

    assert step.rationale == "先缩小候选池，再决定是否需要研报"
    assert step.success_criteria == "返回候选代码；说明不能直接买入的边界"
    assert step.risk_guard == "write: 不写入推荐或持仓"
    assert payload["rationale"] == step.rationale
    assert payload["success_criteria"] == step.success_criteria
    assert payload["risk_guard"] == step.risk_guard


def test_workflow_planner_accepts_top_level_task_script():
    run = plan_workflow(
        "用 workflow 诊断 300750",
        context=route_workflow("用 workflow 诊断 300750"),
        workflow_script={
            "title": "单股诊断",
            "steps": [{"id": "structure", "role": "分析", "task": "诊断 300750 的量价结构"}],
        },
    )

    assert len(run.steps) == 1
    assert run.steps[0].agent == "task"
    assert run.steps[0].phase == "top_level"
    assert run.steps[0].prompt == "诊断 300750 的量价结构"


def test_workflow_planner_accepts_keyed_phase_and_task_objects():
    run = plan_workflow(
        "用 workflow 做完整选股和攻防计划",
        context=route_workflow("用 workflow 做完整选股和攻防计划"),
        workflow_script={
            "title": "对象式脚本",
            "phases": {
                "collect": {
                    "tasks": {
                        "scan": {"title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描今日候选"},
                        "market": {"title": "读取水温", "tools": ["get_market_overview"], "prompt": "读取市场水温"},
                    }
                },
                "decision": {
                    "tasks": {
                        "plan": {
                            "title": "攻防计划",
                            "tools": ["generate_strategy_decision"],
                            "after": ["scan", "market"],
                            "prompt": "整合候选和市场水温输出攻防计划",
                        }
                    }
                },
            },
        },
    )

    assert [step.step_id for step in run.steps] == ["scan", "market", "plan"]
    assert [step.phase for step in run.steps] == ["collect", "collect", "decision"]
    assert [step.tool_scope for step in run.steps] == [
        ("screen_stocks",),
        ("get_market_overview",),
        ("generate_strategy_decision",),
    ]
    assert run.steps[2].depends_on == ("scan", "market")


def test_workflow_planner_splits_inline_tool_and_dependency_fields():
    run = plan_workflow(
        "用 workflow 做候选扫描和市场水温后再决策",
        context=route_workflow("用 workflow 做候选扫描和市场水温后再决策"),
        workflow_script={
            "title": "逗号字段脚本",
            "tasks": [
                {
                    "id": "scan",
                    "title": "扫描候选",
                    "tools": "screen_stocks，get_market_overview",
                    "prompt": "扫描候选并读取市场水温",
                },
                {
                    "id": "plan",
                    "title": "生成攻防计划",
                    "tool": "generate_strategy_decision",
                    "depends_on": "scan, market",
                    "prompt": "基于候选和市场环境生成攻防计划",
                },
            ],
        },
    )

    assert run.steps[0].tool_scope == ("screen_stocks", "get_market_overview")
    assert run.steps[1].tool_scope == ("generate_strategy_decision",)
    assert run.steps[1].depends_on == ("scan", "market")


def test_workflow_planner_keeps_subtasks_without_agent_fields():
    run = plan_workflow(
        "帮我做今日选股",
        context=WORKFLOWS["stock_screen"],
        workflow_script={
            "title": "自然拆分选股",
            "phases": [
                {
                    "id": "screen",
                    "subtasks": [
                        {"id": "collect", "title": "收集候选", "prompt": "跑全市场候选扫描"},
                        {"id": "review", "title": "复核结构", "after": "collect", "instructions": "复核候选结构"},
                    ],
                }
            ],
        },
    )

    assert [step.step_id for step in run.steps] == ["collect", "review"]
    assert [step.agent for step in run.steps] == ["task", "task"]
    assert [step.tools for step in run.steps] == [(), ()]
    assert run.steps[1].depends_on == ("collect",)
    assert run.steps[1].prompt == "复核候选结构"


def test_workflow_planner_fallback_uses_generic_task_executor():
    run = plan_workflow(
        "用 workflow 完整做一遍今天的 A 股选股，给出候选、理由和买卖计划",
        context=route_workflow("用 workflow 完整做一遍今天的 A 股选股，给出候选、理由和买卖计划"),
    )

    assert len(run.steps) == 1
    assert run.steps[0].agent == "task"
    assert run.steps[0].tools == ()
    assert "用户原文" in run.steps[0].prompt
    assert "A 股选股" in run.steps[0].prompt


def test_workflow_planner_fallback_keeps_typo_like_task_model_authored():
    run = plan_workflow(
        "用 workflow 给我做磁场诊断",
        context=route_workflow("用 workflow 给我做磁场诊断"),
    )

    assert len(run.steps) == 1
    assert run.script["title"] == "用 workflow 给我做磁场诊断"
    assert run.steps[0].agent == "task"
    assert run.steps[0].tools == ()
    assert run.steps[0].title == "用 workflow 给我做磁场诊断"
    assert "sub-agent" not in run.steps[0].title
    assert "自然语言语义" in run.steps[0].prompt
    assert "常见别字" not in run.steps[0].prompt
    assert "磁场诊断" in run.steps[0].prompt


def test_workflow_planner_treats_tool_named_tasks_as_task_scopes():
    run = plan_workflow(
        "用 workflow 做选股和攻防计划",
        context=route_workflow("用 workflow 做选股和攻防计划"),
        workflow_script={
            "title": "工具式脚本",
            "steps": [
                {"id": "scan", "title": "扫描候选", "tool": "screen_stocks", "prompt": "扫描今日候选"},
                {
                    "id": "plan",
                    "title": "攻防计划",
                    "tool": {"name": "generate_strategy_decision"},
                    "after": "scan",
                    "prompt": "输出候选攻防计划",
                },
            ],
        },
    )

    assert [step.agent for step in run.steps] == ["task", "task"]
    assert [step.tools for step in run.steps] == [(), ()]
    assert [step.tool_scope for step in run.steps] == [("screen_stocks",), ("generate_strategy_decision",)]
    assert run.steps[1].depends_on == ("scan",)


def test_workflow_step_context_includes_outcome_metadata():
    step = WorkflowStep(
        step_id="scan",
        title="扫描候选",
        phase="collect",
        rationale="先缩小候选池",
        success_criteria="输出候选和风险边界",
        risk_guard="不写入推荐或持仓",
        context="只读运行",
    )

    context = _step_context(step, [])

    assert "task rationale:\n先缩小候选池" in context
    assert "success criteria:\n输出候选和风险边界" in context
    assert "risk guard:\n不写入推荐或持仓" in context
    assert "task context:\n只读运行" in context


def test_workflow_handoff_state_compacts_candidate_context():
    tools = StubToolRegistry()
    tools._tool_context = SimpleNamespace(
        state={
            "last_screen_result": {
                "scan_scope": {"source": "screen_stocks"},
                "selection_brief": {"status": "ready_for_ai_review", "best_codes": ["300750"]},
                "action_plan": {
                    "candidate_action": "generate_ai_report",
                    "new_buy_allowed": False,
                    "ai_review_allowed": True,
                    "trade_readiness": "research_only",
                    "review_targets": {"codes": ["300750"], "tool": "generate_ai_report"},
                },
                "symbols_for_report": [
                    {
                        "code": "300750",
                        "name": "宁德时代",
                        "tag": "推荐评估候选",
                        "track": "Trend",
                        "stage": "Markup",
                        "candidate_lane": "mainline",
                        "entry_type": "launchpad",
                        "selection_source": "recommendation_event_eval",
                        "source_type": "policy_selection",
                        "priority_rank": 1,
                        "priority_score": 91.2,
                        "shadow_score": 88.4,
                        "score": 12.5,
                        "selection_strategy": "candidate_shadow_then_score",
                        "recommend_date": "2026-06-30",
                        "is_ai_recommended": True,
                        "funnel_score": 89.5,
                        "recommend_count": 2,
                        "candidate_shadow_score": 92.0,
                        "candidate_shadow_grade": "S",
                        "entry_quality_score": 84.0,
                        "entry_quality_grade": "A",
                        "entry_quality_risk_flags": ["短线涨幅偏快"],
                        "label_ready": False,
                        "label_status": "pending",
                        "rank_reason": "推荐评估候选#1；候选影子评级 S",
                        "quality_factors": ["高优先级研报候选"],
                        "risk_factors": ["不直接买入"],
                        "action_status": "ready_for_ai_review",
                        "next_step": "生成 AI 研报",
                    }
                ],
                "trigger_groups": [{"large": "omitted"}],
            }
        }
    )

    handoff = _workflow_handoff_state(tools)

    screen = handoff["last_screen_result"]
    assert screen["selection_brief"]["best_codes"] == ["300750"]
    assert screen["action_plan"]["new_buy_allowed"] is False
    candidate = screen["symbols_for_report"][0]
    assert candidate["code"] == "300750"
    assert candidate["candidate_shadow_score"] == 92.0
    assert candidate["entry_quality_score"] == 84.0
    assert candidate["funnel_score"] == 89.5
    assert candidate["selection_strategy"] == "candidate_shadow_then_score"
    assert candidate["is_ai_recommended"] is True
    assert candidate["label_ready"] is False
    assert "trigger_groups" not in screen


def test_workflow_synthesis_receives_step_handoff_state(tmp_path, monkeypatch):
    from integrations import local_db

    def _synthesis_round(messages, _tools, _system_prompt):
        content = messages[0]["content"]
        assert '"handoff_state"' in content
        assert '"last_screen_result"' in content
        assert '"300750"' in content
        return [{"type": "text_delta", "text": "已基于候选 handoff 汇总。"}]

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-handoff.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    tools = StubToolRegistry()
    tools._tool_context = SimpleNamespace(
        state={
            "last_screen_result": {
                "selection_brief": {"status": "ready_for_ai_review", "best_codes": ["300750"]},
                "symbols_for_report": [{"code": "300750", "name": "宁德时代"}],
            }
        }
    )
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "已完成候选扫描。"}],
            _synthesis_round,
        ]
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_handoff",
        user_text="用 workflow 选出好股票",
        workflow_context=route_workflow("用 workflow 选出好股票"),
        workflow_script={"tasks": [{"id": "scan", "title": "扫描候选", "prompt": "扫描候选"}]},
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 选出好股票"}]))

    try:
        done_event = next(event for event in events if event["type"] == "workflow_step_done")
        assert (
            done_event["source"]["agent_detail"]["handoff_state"]["last_screen_result"]["symbols_for_report"][0]["code"]
            == "300750"
        )
        assert events[-1]["text"] == "已基于候选 handoff 汇总。"
    finally:
        _reset_local_db(local_db)


def test_workflow_synthesis_prompt_requires_candidate_answer_contract():
    run = WorkflowRun(
        run_id="wf_contract",
        session_id="s_contract",
        user_text="帮我完整做一遍今天的 A 股选股，给出候选、理由和买卖计划",
        context=WORKFLOWS["dynamic_task"],
        script={"synthesis_prompt": "输出候选、理由和买卖计划。"},
    )
    results = [
        {
            "step": {"step_id": "scan", "title": "扫描候选"},
            "result": {
                "handoff_state": {
                    "last_screen_result": {
                        "action_plan": {"new_buy_allowed": False, "trade_readiness": "research_only"},
                        "symbols_for_report": [
                            {
                                "code": "300750",
                                "name": "宁德时代",
                                "candidate_shadow_score": 92.0,
                                "candidate_shadow_grade": "S",
                                "entry_quality_score": 84.0,
                                "entry_quality_grade": "A",
                                "risk_factors": ["评估标签尚未成熟"],
                                "next_step": "生成 AI 研报",
                            }
                        ],
                    }
                }
            },
        }
    ]

    prompt = _synthesis_prompt(run, results)

    assert "必须按候选分层输出" in prompt
    assert "priority_score/shadow_score/funnel_score" in prompt
    assert "candidate_shadow_score/grade" in prompt
    assert "entry_quality_score/grade" in prompt
    assert "new_buy_allowed=false" in prompt
    assert "trade_readiness=research_only" in prompt
    assert "不得写成买入建议" in prompt
    assert '"candidate_shadow_score": 92.0' in prompt


def test_workflow_synthesis_prioritizes_handoff_before_long_agent_results():
    run = WorkflowRun(
        run_id="wf_long_handoff",
        session_id="s_long_handoff",
        user_text="帮我选出今天最值得复核的股票",
        context=WORKFLOWS["dynamic_task"],
        script={"synthesis_prompt": "优先汇总候选。"},
    )
    handoff = {
        "last_screen_result": {
            "symbols_for_report": [
                {
                    "code": "300750",
                    "name": "宁德时代",
                    "candidate_shadow_score": 92.0,
                    "candidate_shadow_grade": "S",
                    "next_step": "生成 AI 研报",
                }
            ]
        }
    }
    results = [
        {
            "step": {"step_id": "scan", "title": "扫描候选"},
            "result": {"status": "completed", "result": "x" * 13000, "handoff_state": handoff},
        }
    ]

    prompt = _synthesis_prompt(run, results)
    handoff_section = prompt.split("priority candidate handoff:\n", 1)[1].split("\n\nagent results:", 1)[0]
    agent_results_section = prompt.split("agent results:\n", 1)[1]

    assert '"candidate_shadow_score": 92.0' in handoff_section
    assert '"300750"' in handoff_section
    assert '"candidate_shadow_score": 92.0' not in agent_results_section


def test_workflow_executor_waits_step_background_tasks_for_handoff(tmp_path, monkeypatch):
    from integrations import local_db

    class BackgroundHandoffTools(StubToolRegistry):
        def __init__(self):
            super().__init__(tool_results={"screen_stocks": {"status": "background", "task_id": "bg_screen"}})
            self._tool_context = SimpleNamespace(state={})
            self.wait_calls: list[dict[str, object]] = []

        def wait_background_tasks(self, task_ids, timeout_seconds=30.0):
            self.wait_calls.append({"task_ids": list(task_ids), "timeout_seconds": timeout_seconds})
            self._tool_context.state["last_screen_result"] = {
                "selection_brief": {"status": "ready_for_ai_review", "best_codes": ["300750"]},
                "symbols_for_report": [{"code": "300750", "name": "宁德时代"}],
            }
            return [{"task_id": "bg_screen", "tool_name": "screen_stocks", "status": "completed"}]

    def _synthesis_round(messages, _tools, _system_prompt):
        content = messages[0]["content"]
        assert '"background_task_ids": ["bg_screen"]' in content
        assert '"background_tasks": [{"task_id": "bg_screen"' in content
        assert '"symbols_for_report": [{"code": "300750"' in content
        return [{"type": "text_delta", "text": "已等待后台筛选并汇总候选。"}]

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-bg-wait.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    monkeypatch.setenv("WYCKOFF_WORKFLOW_BG_WAIT_SECONDS", "2")
    tools = BackgroundHandoffTools()
    provider = ScriptedProvider(
        rounds=[
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_screen", "name": "screen_stocks", "args": {}}]}],
            [{"type": "text_delta", "text": "筛选已提交后台。"}],
            _synthesis_round,
        ]
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_bg_wait",
        user_text="用 workflow 选出好股票",
        workflow_context=route_workflow("用 workflow 选出好股票"),
        workflow_script={
            "tasks": [{"id": "scan", "title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描候选"}]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 选出好股票"}]))

    try:
        done_event = next(event for event in events if event["type"] == "workflow_step_done")
        detail = done_event["source"]["agent_detail"]
        assert tools.wait_calls == [{"task_ids": ["bg_screen"], "timeout_seconds": 2.0}]
        assert detail["background_task_ids"] == ["bg_screen"]
        assert detail["background_tasks"][0]["status"] == "completed"
        assert detail["handoff_state"]["last_screen_result"]["selection_brief"]["best_codes"] == ["300750"]
        assert events[-1]["text"] == "已等待后台筛选并汇总候选。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_persists_plan_and_steps(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": _PLAN_JSON}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "diagnose"}}],
                }
            ],
            [{"type": "text_delta", "text": "持仓风险低，继续观察。"}],
            [{"type": "text_delta", "text": "持仓复盘完成。"}],
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})

    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s1",
        user_text="用 workflow 复盘我的持仓",
    )
    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 复盘我的持仓"}]))

    assert executor.run is not None
    run = get_workflow_run(executor.run.run_id)
    stored_events = load_workflow_events(executor.run.run_id)
    try:
        assert events[0]["type"] == "workflow_plan"
        assert events[0]["label"] == "持仓复盘"
        assert events[0]["route"]["reason"] == "用户显式要求动态 workflow"
        assert events[0]["plan"]["route"]["matches"] == ["用 workflow"]
        assert events[0]["plan"]["label"] == "持仓复盘"
        assert events[0]["plan"]["script"]["title"] == "持仓复盘"
        assert events[0]["plan"]["steps"][0]["agent"] == "task"
        assert events[0]["plan"]["steps"][0]["tool_scope"] == []
        assert any(event["type"] == "workflow_step_start" for event in events)
        assert any(event["type"] == "workflow_done" for event in events)
        assert events[-1]["type"] == "done"
        assert events[-1]["text"] == "持仓复盘完成。"
        assert "只看核心仓位" in provider.calls[1]["messages"][0]["content"]
        assert "汇总持仓风险和下一步动作" in provider.calls[3]["messages"][0]["content"]
        assert run and run["status"] == "completed"
        assert run["workflow"] == "dynamic_task"
        assert run["label"] == "持仓复盘"
        assert run["plan"]["script"]["runtime"]["script_path"].startswith(str(tmp_path / "workflow-runs"))
        assert (tmp_path / "workflow-runs" / "s1" / f"{executor.run.run_id}.json").is_file()
        assert "措辞恢复" not in provider.calls[0]["system_prompt"]
        assert "错别字" not in provider.calls[0]["system_prompt"]
        assert "运行上下文" in provider.calls[0]["messages"][0]["content"]
        assert stored_events[0]["event_type"] == "workflow_plan"
        done_event = next(row for row in stored_events if row["event_type"] == "workflow_step_done")
        detail = done_event["payload"]["source"]["agent_detail"]
        assert detail["step_id"] == "read_positions"
        assert detail["tool_calls"] == ["portfolio"]
        assert "持仓风险低" in detail["result"]
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_scopes_sub_agent_tools_per_step(tmp_path, monkeypatch):
    from integrations import local_db

    def _portfolio_only_round(_messages, tools, _system_prompt):
        assert {schema["name"] for schema in tools} == {"portfolio"}
        return [{"type": "tool_calls", "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {}}]}]

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    schemas = [
        {"name": "portfolio", "description": "Mock portfolio tool", "parameters": {"type": "object"}},
        {"name": "analyze_stock", "description": "Mock analyze tool", "parameters": {"type": "object"}},
        {"name": "generate_ai_report", "description": "Mock report tool", "parameters": {"type": "object"}},
    ]
    provider = ScriptedProvider(
        rounds=[
            _portfolio_only_round,
            [{"type": "text_delta", "text": "已读取持仓。"}],
            [{"type": "text_delta", "text": "持仓摘要完成。"}],
        ]
    )
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(schemas=schemas, tool_results={"portfolio": {"positions": []}}),
        session_id="s_scope",
        user_text="只读取持仓",
        workflow_context=route_workflow("用 workflow 复核持仓"),
        workflow_script=json.loads(_SCOPED_TOOL_PLAN_JSON),
    )

    events = list(executor.run_stream([{"role": "user", "content": "只读取持仓"}]))

    try:
        done_event = next(event for event in events if event["type"] == "workflow_step_done")
        detail = done_event["source"]["agent_detail"]
        assert events[0]["plan"]["steps"][0]["tool_scope"] == ["portfolio"]
        assert detail["tool_scope"] == ["portfolio"]
        assert detail["tool_calls"] == ["portfolio"]
        assert events[-1]["text"] == "持仓摘要完成。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_bounds_generic_task_tools_by_workflow_context(tmp_path, monkeypatch):
    from integrations import local_db

    def _bounded_round(_messages, tools, _system_prompt):
        exposed = {schema["name"] for schema in tools}
        assert "portfolio" in exposed
        assert "ask_user_question" in exposed
        assert "run_backtest" not in exposed
        return [{"type": "text_delta", "text": "已按持仓上下文复盘。"}]

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            _bounded_round,
            [{"type": "text_delta", "text": "复盘完成。"}],
        ]
    )
    schemas = [
        {"name": "portfolio", "description": "Mock portfolio tool", "parameters": {"type": "object"}},
        {"name": "run_backtest", "description": "Mock backtest tool", "parameters": {"type": "object"}},
        {"name": "ask_user_question", "description": "Mock ask tool", "parameters": {"type": "object"}},
    ]
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(schemas=schemas, tool_results={"portfolio": {"positions": []}}),
        session_id="s_bound",
        user_text="复盘持仓",
        workflow_context=WORKFLOWS["portfolio_review"],
        workflow_script={
            "title": "持仓动态任务",
            "tasks": [{"id": "review", "title": "复盘持仓", "prompt": "读取持仓并判断风险"}],
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "复盘持仓"}]))

    try:
        assert events[0]["plan"]["steps"][0]["agent"] == "task"
        assert events[-1]["text"] == "复盘完成。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_reruns_stored_script_without_replanning(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "diagnose"}}],
                }
            ],
            [{"type": "text_delta", "text": "复跑后的持仓风险低。"}],
            [{"type": "text_delta", "text": "已按原脚本复跑完成。"}],
        ]
    )
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(tool_results={"portfolio": {"positions": []}}),
        session_id="s2",
        user_text="复跑 workflow wf_old",
        workflow_context=route_workflow("用 workflow 复盘我的持仓"),
        workflow_script=json.loads(_PLAN_JSON),
        source_run_id="wf_old",
    )

    events = list(executor.run_stream([{"role": "user", "content": "复跑 workflow wf_old"}]))

    try:
        assert events[0]["type"] == "workflow_plan"
        assert events[0]["plan"]["script"]["runtime"]["rerun_of"] == "wf_old"
        assert events[-1]["text"] == "已按原脚本复跑完成。"
        assert len(provider.calls) == 3
        assert "动态 workflow 编排器" not in provider.calls[0]["system_prompt"]
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_runs_same_phase_tasks_in_parallel(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "研究视角完成。"}],
            [{"type": "text_delta", "text": "结构视角完成。"}],
            [{"type": "text_delta", "text": "两个视角已合并。"}],
        ]
    )
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(),
        session_id="s3",
        user_text="并发复核 300750",
        workflow_context=route_workflow("用 workflow 并发复核 300750"),
        workflow_script=json.loads(_PARALLEL_PLAN_JSON),
        workflow_args="300750",
    )

    events = list(executor.run_stream([{"role": "user", "content": "并发复核 300750"}]))

    try:
        phase_start = next(event for event in events if event["type"] == "workflow_phase_start")
        step_starts = [event for event in events if event["type"] == "workflow_step_start"]
        step_dones = [event for event in events if event["type"] == "workflow_step_done"]
        assert phase_start["parallel"] is True
        assert len(step_starts) == 2
        assert len(step_dones) == 2
        assert events.index(step_starts[0]) < events.index(step_dones[0])
        assert events.index(step_starts[1]) < events.index(step_dones[0])
        assert "本次运行输入" in provider.calls[0]["messages"][0]["content"]
        assert "300750" in provider.calls[0]["messages"][0]["content"]
        assert events[-1]["text"] == "两个视角已合并。"
    finally:
        _reset_local_db(local_db)


def test_parallel_workflow_synthesis_keeps_script_order(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ParallelResultProvider()
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(),
        session_id="s_parallel_order",
        user_text="并发复核 300750",
        workflow_context=route_workflow("用 workflow 并发复核 300750"),
        workflow_script=json.loads(_PARALLEL_PLAN_JSON),
    )

    events = list(executor.run_stream([{"role": "user", "content": "并发复核 300750"}]))

    try:
        done_steps = [event["step"]["step_id"] for event in events if event["type"] == "workflow_step_done"]
        assert done_steps == ["analysis_view", "research_view"]
        assert provider.synthesis_prompt.index('"step_id": "research_view"') < provider.synthesis_prompt.index(
            '"step_id": "analysis_view"'
        )
        assert events[-1]["text"] == "两个视角已按脚本顺序合并。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_respects_task_dependencies_within_phase(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "扫描完成，候选 A。"}],
            [{"type": "text_delta", "text": "基于候选 A 制定攻防计划。"}],
            [{"type": "text_delta", "text": "依赖复核完成。"}],
        ]
    )
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(),
        session_id="s_dep",
        user_text="按依赖复核候选",
        workflow_context=route_workflow("用 workflow 复核候选"),
        workflow_script=json.loads(_DEPENDENT_PLAN_JSON),
    )

    events = list(executor.run_stream([{"role": "user", "content": "按依赖复核候选"}]))

    try:
        step_starts = [event for event in events if event["type"] == "workflow_step_start"]
        step_dones = [event for event in events if event["type"] == "workflow_step_done"]
        phase_starts = [event for event in events if event["type"] == "workflow_phase_start"]
        assert [event["step"]["step_id"] for event in step_starts] == ["scan", "risk_plan"]
        assert step_starts[1]["step"]["depends_on"] == ["scan"]
        assert events.index(step_dones[0]) < events.index(step_starts[1])
        assert [event["parallel"] for event in phase_starts] == [False, False]
        assert "depends_on=scan" in provider.calls[1]["messages"][0]["content"]
        assert "扫描完成，候选 A。" in provider.calls[1]["messages"][0]["content"]
        assert events[-1]["text"] == "依赖复核完成。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_topologically_orders_out_of_order_dependencies(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "扫描完成，候选 A。"}],
            [{"type": "text_delta", "text": "基于候选 A 制定攻防计划。"}],
            [{"type": "text_delta", "text": "乱序依赖复核完成。"}],
        ]
    )
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(),
        session_id="s_dep_order",
        user_text="按依赖复核候选",
        workflow_context=route_workflow("用 workflow 复核候选"),
        workflow_script=json.loads(_OUT_OF_ORDER_DEPENDENT_PLAN_JSON),
    )

    events = list(executor.run_stream([{"role": "user", "content": "按依赖复核候选"}]))

    try:
        step_starts = [event for event in events if event["type"] == "workflow_step_start"]
        assert [event["step"]["step_id"] for event in step_starts] == ["scan", "risk_plan"]
        assert "先扫描候选" in provider.calls[0]["messages"][0]["content"]
        assert "扫描完成，候选 A。" in provider.calls[1]["messages"][0]["content"]
        assert events[-1]["text"] == "乱序依赖复核完成。"
    finally:
        _reset_local_db(local_db)


def test_phase_batches_tolerates_external_and_cyclic_dependencies():
    external = WorkflowStep(step_id="external", title="外部依赖", phase="review", depends_on=("prior_phase",))
    free = WorkflowStep(step_id="free", title="无依赖", phase="review")
    assert [[step.step_id for step in batch] for batch in _phase_batches([external, free])] == [["external", "free"]]

    a = WorkflowStep(step_id="a", title="A", phase="cycle", depends_on=("b",))
    b = WorkflowStep(step_id="b", title="B", phase="cycle", depends_on=("a",))
    assert [[step.step_id for step in batch] for batch in _phase_batches([a, b])] == [["a"], ["b"]]


def test_prepared_workflow_can_be_stopped_before_agents_run(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    executor = WorkflowExecutor(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s4",
        user_text="复跑 workflow wf_old",
        workflow_context=route_workflow("用 workflow 复盘我的持仓"),
        workflow_script=json.loads(_PLAN_JSON),
        source_run_id="wf_old",
    )
    plan = executor.prepare_run()
    control = WorkflowControl(plan["run_id"])
    control.stop()
    executor.set_control(control)

    events = list(executor.run_stream([{"role": "user", "content": "复跑 workflow wf_old"}]))

    try:
        run = get_workflow_run(plan["run_id"])
        assert events[0]["type"] == "workflow_start"
        assert any(event["type"] == "workflow_stopped" for event in events)
        assert events[-1]["text"] == "workflow 已停止。已完成步骤可在 /workflow show 查看。"
        assert run and run["status"] == "stopped"
    finally:
        _reset_local_db(local_db)


def test_prepared_workflow_can_reload_edited_script(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    executor = WorkflowExecutor(
        ScriptedProvider([]),
        StubToolRegistry(),
        session_id="s5",
        user_text="复跑 workflow wf_old",
        workflow_context=route_workflow("用 workflow 复盘我的持仓"),
        workflow_script=json.loads(_PLAN_JSON),
        source_run_id="wf_old",
    )
    plan = executor.prepare_run()

    event = executor.replace_prepared_script(json.loads(_EDITED_PLAN_JSON))

    try:
        run = get_workflow_run(plan["run_id"])
        assert event["run_id"] == plan["run_id"]
        assert event["plan"]["script"]["title"] == "编辑后脚本"
        assert event["plan"]["steps"][0]["step_id"] == "edited_task"
        assert run and run["plan"]["script"]["title"] == "编辑后脚本"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_restarts_only_selected_step(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "结构视角重启完成。"}],
            [{"type": "text_delta", "text": "单 task 重启完成。"}],
        ]
    )
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(),
        session_id="s6",
        user_text="重启 workflow wf_old 的 task analysis_view",
        workflow_context=route_workflow("用 workflow 并发复核 300750"),
        workflow_script=json.loads(_PARALLEL_PLAN_JSON),
        source_run_id="wf_old",
        only_step_id="analysis_view",
    )

    events = list(executor.run_stream([{"role": "user", "content": "restart"}]))

    try:
        starts = [event for event in events if event["type"] == "workflow_step_start"]
        assert len(starts) == 1
        assert starts[0]["step"]["step_id"] == "analysis_view"
        assert events[0]["plan"]["script"]["runtime"]["only_step_id"] == "analysis_view"
        assert events[-1]["text"] == "单 task 重启完成。"
    finally:
        _reset_local_db(local_db)


def test_build_resume_prompt_includes_step_state():
    prompt = build_resume_prompt(
        {
            "run_id": "wf_1",
            "label": "持仓复盘",
            "status": "completed",
            "user_text": "我的持仓怎么样",
            "plan": {
                "steps": [
                    {"status": "completed", "title": "读取持仓与资金", "summary": "portfolio: ok"},
                    {"status": "skipped", "title": "形成去留和风险动作", "summary": ""},
                ]
            },
        }
    )

    assert "继续 workflow wf_1" in prompt
    assert "[completed] 读取持仓与资金 portfolio: ok" in prompt
    assert "不要重复已完成工具调用" in prompt
