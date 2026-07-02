from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from types import SimpleNamespace

from cli.tools import TOOL_SCHEMAS
from cli.workflows.control import WorkflowControl
from cli.workflows.executor import (
    WorkflowExecutor,
    _candidate_conclusion_from_handoff,
    _fallback_handoff_lines,
    _fallback_summary,
    _phase_batches,
    _step_context,
    _synthesis_handoff_summary,
    _synthesis_prompt,
    _workflow_handoff_state,
)
from cli.workflows.models import WorkflowRun, WorkflowStep
from cli.workflows.planner import _PLAN_SYSTEM_PROMPT, MAX_WORKFLOW_STEPS, plan_workflow
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
    assert "工具是脚本契约" in _PLAN_SYSTEM_PROMPT
    assert "精确工具名填写 tools" in _PLAN_SYSTEM_PROMPT
    assert "无工具占位 task" in _PLAN_SYSTEM_PROMPT
    assert "runtime 会跨 phase 按依赖顺序切批执行" in _PLAN_SYSTEM_PROMPT
    assert "depends_on 指向提供这些事实的 task id" in _PLAN_SYSTEM_PROMPT
    assert "depends_on 指向前序 task" not in _PLAN_SYSTEM_PROMPT
    assert "必须出现 screen_stocks" in _PLAN_SYSTEM_PROMPT
    assert "generate_strategy_decision" in _PLAN_SYSTEM_PROMPT


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


def test_model_generated_workflow_script_is_trimmed_before_persistence():
    tasks = [
        {"id": f"task_{index}", "title": f"复核候选 {index}", "prompt": f"复核候选 {index}"}
        for index in range(MAX_WORKFLOW_STEPS + 3)
    ]
    provider = ScriptedProvider(
        [
            [
                {
                    "type": "text_delta",
                    "text": json.dumps(
                        {"title": "过长选股计划", "phases": [{"id": "review", "tasks": tasks}]},
                        ensure_ascii=False,
                    ),
                }
            ]
        ]
    )

    run = plan_workflow(
        "帮我选出好股票",
        context=WORKFLOWS["dynamic_task"],
        provider=provider,
        tools=StubToolRegistry(),
    )

    runtime = run.script["runtime"]
    assert len(run.steps) == MAX_WORKFLOW_STEPS
    assert len(run.script["phases"][0]["tasks"]) == MAX_WORKFLOW_STEPS
    assert run.steps[-1].step_id == f"task_{MAX_WORKFLOW_STEPS - 1}"
    assert runtime["planner"] == "model_script"
    assert runtime["step_limit"] == MAX_WORKFLOW_STEPS
    assert runtime["original_step_count"] == MAX_WORKFLOW_STEPS + 3
    assert runtime["truncated_step_count"] == 3


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
    assert run.script["runtime"] == {
        "planner": "fallback_script",
        "fallback_reason": "provider unavailable",
    }


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
    assert run.script["runtime"]["planner"] == "fallback_script"


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
                "theme_context": {
                    "event_mainlines": "机器人 0.82/爆发",
                    "today_activity": "机器人 0.76/活跃",
                    "theme_radar": "人形机器人 0.78/confirmed",
                    "theme_radar_source": "current",
                    "hot_concepts": ["机器人", "灵巧手", "滚柱丝杠", "电子皮肤", "控制系统", "减速器", "extra"],
                },
                "selection_brief": {"status": "ready_for_ai_review", "best_codes": ["300750"]},
                "action_plan": {
                    "candidate_action": "generate_ai_report",
                    "new_buy_allowed": False,
                    "ai_review_allowed": True,
                    "trade_readiness": "research_only",
                    "quality_gate": {
                        "status": "blocked_by_quality_gate",
                        "reason": "000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00",
                    },
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
                        "strategic_theme": "机器人",
                        "theme_score": 0.72,
                        "theme_source": "ths_hot_event",
                        "theme_event_id": "evt-robot",
                        "theme_event_title": "特斯拉量产临近，机器人板块还能回归市场主线吗？",
                        "theme_event_reason": "灵巧手",
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
                        "candidate_quality_score": 92.0,
                        "risk_adjusted_quality_score": 87.0,
                        "entry_risk_penalty": 5.0,
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
                "watch_candidates": [
                    {
                        "code": "000013",
                        "name": "低质量候选",
                        "action_status": "watch_only",
                        "risk_adjusted_quality_score": 65.0,
                    }
                ],
                "quality_gate": {
                    "status": "blocked_by_quality_gate",
                    "reason": "000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00",
                },
                "trigger_groups": [{"large": "omitted"}],
                "candidate_guard_summary": {
                    "direct_buy_blocked_count": 1,
                    "message": "以下候选仅可复核或观察，禁止直接买入",
                    "candidates": [
                        {
                            "code": "300750",
                            "name": "宁德时代",
                            "reason": "候选标签未成熟，禁止直接买入",
                            "action_status": "ready_for_ai_review",
                            "label_ready": False,
                        }
                    ],
                },
            },
            "last_ai_report": {
                "ok": True,
                "model": "gpt-test",
                "stock_count": 1,
                "reviewed_codes": ["300750"],
                "reviewed_symbols": [
                    {
                        "code": "300750",
                        "name": "宁德时代",
                        "action_status": "ready_for_ai_review",
                        "label_ready": False,
                    }
                ],
                "candidate_guard_summary": {
                    "direct_buy_blocked_count": 1,
                    "message": "以下候选仅可复核或观察，禁止直接买入",
                    "candidates": [
                        {
                            "code": "300750",
                            "name": "宁德时代",
                            "reason": "候选标签未成熟，禁止直接买入",
                            "action_status": "ready_for_ai_review",
                            "label_ready": False,
                            "risk_factors": ["最新候选的未来窗口标签尚未成熟"],
                        }
                    ],
                },
            },
            "last_strategy_decision": {
                "status": "skipped_notify_unconfigured",
                "report_source": "last_ai_report",
                "candidate_count": 1,
                "reviewed_codes": ["300750"],
                "reviewed_symbols": [
                    {
                        "code": "300750",
                        "name": "宁德时代",
                        "action_status": "ready_for_ai_review",
                        "label_ready": False,
                        "risk_factors": ["最新候选的未来窗口标签尚未成熟"],
                    }
                ],
                "candidate_guard_summary": {
                    "direct_buy_blocked_count": 1,
                    "message": "以下候选仅可复核或观察，禁止直接买入",
                    "candidates": [
                        {
                            "code": "300750",
                            "name": "宁德时代",
                            "reason": "候选标签未成熟，禁止直接买入",
                            "action_status": "ready_for_ai_review",
                            "label_ready": False,
                            "risk_factors": ["最新候选的未来窗口标签尚未成熟"],
                            "debug_payload": "omitted",
                        }
                    ],
                },
            },
        }
    )

    handoff = _workflow_handoff_state(tools)

    screen = handoff["last_screen_result"]
    assert screen["selection_brief"]["best_codes"] == ["300750"]
    assert screen["theme_context"]["event_mainlines"] == "机器人 0.82/爆发"
    assert screen["theme_context"]["hot_concepts"] == ["机器人", "灵巧手", "滚柱丝杠", "电子皮肤", "控制系统", "减速器"]
    assert screen["action_plan"]["new_buy_allowed"] is False
    assert screen["action_plan"]["quality_gate"]["status"] == "blocked_by_quality_gate"
    assert screen["quality_gate"]["status"] == "blocked_by_quality_gate"
    candidate = screen["symbols_for_report"][0]
    assert candidate["code"] == "300750"
    assert candidate["candidate_shadow_score"] == 92.0
    assert candidate["entry_quality_score"] == 84.0
    assert candidate["funnel_score"] == 89.5
    assert candidate["candidate_quality_score"] == 92.0
    assert candidate["risk_adjusted_quality_score"] == 87.0
    assert candidate["entry_risk_penalty"] == 5.0
    assert candidate["selection_strategy"] == "candidate_shadow_then_score"
    assert candidate["is_ai_recommended"] is True
    assert candidate["label_ready"] is False
    assert candidate["strategic_theme"] == "机器人"
    assert candidate["theme_source"] == "ths_hot_event"
    assert candidate["theme_event_id"] == "evt-robot"
    assert candidate["theme_event_reason"] == "灵巧手"
    assert screen["watch_candidates"][0]["code"] == "000013"
    screen_guard = screen["candidate_guard_summary"]
    assert screen_guard["candidates"][0]["reason"] == "候选标签未成熟，禁止直接买入"
    report_guard = handoff["last_ai_report"]["candidate_guard_summary"]
    assert report_guard["candidates"][0]["reason"] == "候选标签未成熟，禁止直接买入"
    guard = handoff["last_strategy_decision"]["candidate_guard_summary"]
    assert guard["direct_buy_blocked_count"] == 1
    assert guard["candidates"][0]["reason"] == "候选标签未成熟，禁止直接买入"
    assert guard["candidates"][0]["label_ready"] is False
    assert "debug_payload" not in guard["candidates"][0]
    assert "trigger_groups" not in screen


def test_workflow_handoff_candidate_rows_rank_before_limit():
    tools = StubToolRegistry()
    low_rows = [
        {
            "code": f"00000{index}",
            "name": f"观察候选{index}",
            "action_status": "watch_only",
            "candidate_shadow_score": 20 + index,
        }
        for index in range(6)
    ]
    tools._tool_context = SimpleNamespace(
        state={
            "last_screen_result": {
                "symbols_for_report": [
                    *low_rows,
                    {
                        "code": "300999",
                        "name": "高质量候选",
                        "status": "candidate",
                        "selected_for_report": True,
                        "risk_adjusted_quality_score": 91.0,
                    },
                ]
            }
        }
    )

    handoff = _workflow_handoff_state(tools)

    rows = handoff["last_screen_result"]["symbols_for_report"]
    codes = [row["code"] for row in rows]
    assert len(rows) == 6
    assert codes[0] == "300999"
    assert "000000" not in codes
    assert rows[0]["selected_for_report"] is True
    assert rows[0]["status"] == "candidate"


def test_workflow_handoff_state_preserves_recommendation_candidate_guard():
    tools = StubToolRegistry()
    tools._tool_context = SimpleNamespace(
        state={
            "last_recommendation_event_eval": {
                "result_summary": "推荐事件评估完成",
                "policy_selection": {
                    "status": "candidate",
                    "selection_strategy": "candidate_shadow_then_score",
                    "top_k": 1,
                    "recommend_date": "2026-06-30",
                    "picks": [
                        {
                            "code": "300750",
                            "name": "宁德时代",
                            "action_status": "ready_for_ai_review",
                            "label_ready": False,
                        }
                    ],
                },
                "candidate_guard_summary": {
                    "direct_buy_blocked_count": 1,
                    "message": "以下候选仅可复核或观察，禁止直接买入",
                    "candidates": [
                        {
                            "code": "300750",
                            "name": "宁德时代",
                            "reason": "候选标签未成熟，禁止直接买入",
                            "action_status": "ready_for_ai_review",
                            "label_ready": False,
                            "debug_payload": "omitted",
                        }
                    ],
                },
            }
        }
    )

    handoff = _workflow_handoff_state(tools)

    guard = handoff["last_recommendation_event_eval"]["candidate_guard_summary"]
    assert guard["direct_buy_blocked_count"] == 1
    assert guard["candidates"][0]["reason"] == "候选标签未成熟，禁止直接买入"
    assert "debug_payload" not in guard["candidates"][0]


def test_workflow_handoff_state_normalizes_scalar_candidate_rows():
    tools = StubToolRegistry()
    tools._tool_context = SimpleNamespace(
        state={
            "last_screen_result": {
                "symbols_for_report": ["300750", "宁德时代", {"symbol": "AAPL.US", "name": "Apple"}],
            },
            "last_ai_report": {
                "reviewed_symbols": ["000001"],
            },
        }
    )

    handoff = _workflow_handoff_state(tools)
    summary = _fallback_summary(
        [
            {
                "step": {"title": "扫描候选"},
                "result": {"status": "completed", "result": "扫描完成。", "handoff_state": handoff},
            }
        ]
    )

    screen_rows = handoff["last_screen_result"]["symbols_for_report"]
    assert screen_rows == [{"code": "300750"}, {"name": "宁德时代"}, {"name": "Apple", "code": "AAPL.US"}]
    assert handoff["last_ai_report"]["reviewed_symbols"] == [{"code": "000001"}]
    assert "候选结论: 候选 000001" in summary


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


def test_workflow_explicit_tool_scope_continues_attack_plan_after_screen(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-tool-contract.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
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
            [{"type": "text_delta", "text": "已汇总候选与攻防计划。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=deepcopy(TOOL_SCHEMAS),
        tool_results={
            "screen_stocks": {"symbols_for_report": ["300750"]},
            "generate_strategy_decision": {"status": "skipped_notify_unconfigured", "reviewed_codes": ["300750"]},
        },
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_tool_contract",
        user_text="用 workflow 选出好股票，带风险边界",
        workflow_context=route_workflow("用 workflow 选出好股票，带风险边界"),
        workflow_script={
            "tasks": [
                {
                    "id": "scan_decide",
                    "title": "候选与攻防",
                    "tools": ["screen_stocks", "generate_strategy_decision"],
                    "prompt": "给我找几只值得复核的票，带理由和风险边界",
                }
            ]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 选出好股票，带风险边界"}]))

    try:
        done_event = next(event for event in events if event["type"] == "workflow_step_done")
        detail = done_event["source"]["agent_detail"]
        assert detail["tool_scope"] == ["screen_stocks", "generate_strategy_decision"]
        assert detail["tool_calls"] == ["screen_stocks", "generate_strategy_decision"]
        assert detail["result"] == "攻防计划已基于工具结果生成。"
        assert [call["name"] for call in tools.calls] == ["screen_stocks", "generate_strategy_decision"]
        assert events[-1]["text"] == "已汇总候选与攻防计划。"
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
                                "trade_readiness": "research_only",
                                "new_buy_allowed": False,
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
    assert "candidate_quality_score" in prompt
    assert "risk_adjusted_quality_score" in prompt
    assert "entry_quality_score/grade" in prompt
    assert "new_buy_allowed=false" in prompt
    assert "trade_readiness=research_only" in prompt
    assert "存在 candidate_guard_summary" in prompt
    assert "必须明确哪些候选禁止直接买入" in prompt
    assert "不得写成买入建议" in prompt
    assert '"candidate_shadow_score": 92.0' in prompt
    assert '"new_buy_allowed": false' in prompt


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
            "theme_context": {"event_mainlines": "机器人 0.82/爆发", "today_activity": "机器人 0.76/活跃"},
            "symbols_for_report": [
                {
                    "code": "300750",
                    "name": "宁德时代",
                    "action_status": "ready_for_ai_review",
                    "candidate_shadow_score": 92.0,
                    "candidate_shadow_grade": "S",
                    "candidate_quality_score": 92.0,
                    "risk_adjusted_quality_score": 87.0,
                    "strategic_theme": "机器人",
                    "theme_source": "ths_hot_event",
                    "theme_event_reason": "灵巧手",
                    "quality_factors": ["事件主线:机器人", "候选影子评级 S"],
                    "risk_factors": ["未来窗口标签尚未成熟"],
                    "next_step": "生成 AI 研报",
                }
            ],
        }
    }
    results = [
        {
            "step": {"step_id": "scan", "title": "扫描候选"},
            "result": {"status": "completed", "result": "候选扫描完成。", "handoff_state": handoff},
        }
    ]

    prompt = _synthesis_prompt(run, results)
    handoff_section = prompt.split("priority candidate handoff:\n", 1)[1].split("\n\nagent results:", 1)[0]
    agent_results_section = prompt.split("agent results:\n", 1)[1]

    assert '"candidate_conclusion"' in handoff_section
    assert "候选结论: 首选 300750 宁德时代" in handoff_section
    assert '"candidate_shadow_score": 92.0' in handoff_section
    assert '"risk_adjusted_quality_score": 87.0' in handoff_section
    assert '"theme_context": {"event_mainlines": "机器人 0.82/爆发"' in handoff_section
    assert "事件主线机器人(灵巧手)" in handoff_section
    assert "风险调整分87" in handoff_section
    assert "亮点=事件主线:机器人,候选影子评级 S" in handoff_section
    assert "风险=未来窗口标签尚未成熟" in handoff_section
    assert '"300750"' in handoff_section
    assert '"candidate_shadow_score": 92.0' not in agent_results_section
    assert "候选扫描完成" in agent_results_section
    assert '"handoff_state_ref": "see priority candidate handoff"' in agent_results_section


def test_workflow_synthesis_handoff_summary_dedupes_latest_keys():
    results = [
        {
            "step": {"step_id": "scan", "title": "扫描候选"},
            "result": {
                "handoff_state": {
                    "last_screen_result": {
                        "symbols_for_report": [{"code": "300750", "name": "宁德时代"}],
                    }
                }
            },
        },
        {
            "step": {"step_id": "report", "title": "AI研报"},
            "result": {
                "handoff_state": {
                    "last_screen_result": {
                        "symbols_for_report": [{"code": "300750", "name": "宁德时代", "funnel_score": 89.5}],
                    },
                    "last_ai_report": {"reviewed_codes": ["300750"], "model": "gpt-test"},
                }
            },
        },
        {
            "step": {"step_id": "decision", "title": "攻防决策"},
            "result": {
                "handoff_state": {
                    "last_screen_result": {
                        "symbols_for_report": [
                            {
                                "code": "300750",
                                "name": "宁德时代",
                                "candidate_shadow_score": 92.0,
                                "quality_factors": ["候选影子评级 S"],
                                "risk_factors": ["未来窗口标签尚未成熟"],
                            }
                        ],
                    },
                    "last_ai_report": {"reviewed_codes": ["300750"], "model": "gpt-test"},
                    "last_strategy_decision": {"reviewed_codes": ["300750"], "status": "completed"},
                }
            },
        },
    ]

    summary = _synthesis_handoff_summary(results)

    assert len(summary) == 1
    handoff = summary[0]["handoff_state"]
    assert summary[0]["step_id"] == "decision"
    assert set(handoff) == {"last_screen_result", "last_ai_report", "last_strategy_decision"}
    assert handoff["last_screen_result"]["symbols_for_report"][0]["candidate_shadow_score"] == 92.0
    assert summary[0]["candidate_conclusion"]["evidence"] == ["候选影子92"]
    assert summary[0]["candidate_conclusion"]["quality_factors"] == ["候选影子评级 S"]
    assert summary[0]["candidate_conclusion"]["risk_factors"] == ["未来窗口标签尚未成熟"]
    assert json.dumps(handoff, ensure_ascii=False).count("last_screen_result") == 1


def test_workflow_synthesis_handoff_summary_merges_split_candidate_conclusion():
    results = [
        {
            "step": {"step_id": "scan", "title": "扫描候选"},
            "result": {
                "handoff_state": {
                    "last_screen_result": {
                        "symbols_for_report": [
                            {
                                "code": "300750",
                                "name": "宁德时代",
                                "candidate_shadow_score": 92.0,
                                "candidate_shadow_grade": "S",
                            }
                        ]
                    }
                }
            },
        },
        {
            "step": {"step_id": "decision", "title": "攻防决策"},
            "result": {
                "handoff_state": {
                    "last_strategy_decision": {
                        "reviewed_symbols": [
                            {
                                "code": "300750",
                                "name": "宁德时代",
                                "action_status": "ready_for_ai_review",
                                "next_step": "等待通知配置后生成 OMS 工单",
                            }
                        ]
                    }
                }
            },
        },
    ]

    conclusion = _synthesis_handoff_summary(results)[0]["candidate_conclusion"]

    assert conclusion["source_stage"] == "last_strategy_decision"
    assert conclusion["evidence"] == ["候选影子S/92"]
    assert conclusion["next_step"] == "等待通知配置后生成 OMS 工单"


def test_workflow_synthesis_handoff_summary_derives_guard_from_candidate_fields():
    results = [
        {
            "step": {"step_id": "decision", "title": "攻防决策"},
            "result": {
                "handoff_state": {
                    "last_strategy_decision": {
                        "reviewed_symbols": [
                            {
                                "code": "300750",
                                "name": "宁德时代",
                                "action_status": "ready_for_ai_review",
                                "trade_readiness": "research_only",
                                "new_buy_allowed": False,
                                "next_step": "生成 AI 研报",
                            }
                        ]
                    }
                }
            },
        },
    ]

    conclusion = _synthesis_handoff_summary(results)[0]["candidate_conclusion"]

    assert conclusion["guard_reason"] == "候选未开放新增买入，禁止直接买入"
    assert "候选结论: 受限复核候选 300750 宁德时代" in conclusion["line"]
    assert "护栏=候选未开放新增买入，禁止直接买入" in conclusion["line"]
    assert "交易就绪=research_only" in conclusion["line"]
    assert "不允许新增买入" in conclusion["line"]


def test_workflow_executor_empty_synthesis_uses_candidate_fallback(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-empty-synthesis.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    tools = StubToolRegistry()
    tools._tool_context = SimpleNamespace(
        state={
            "last_screen_result": {
                "symbols_for_report": [
                    {
                        "code": "300750",
                        "name": "宁德时代",
                        "candidate_shadow_score": 92.0,
                        "candidate_shadow_grade": "S",
                        "action_status": "ready_for_ai_review",
                        "trade_readiness": "research_only",
                        "new_buy_allowed": False,
                        "next_step": "生成 AI 研报",
                    }
                ]
            },
            "last_ai_report": {
                "ok": True,
                "model": "gpt-test",
                "stock_count": 1,
                "reviewed_codes": ["300750"],
                "reviewed_symbols": [
                    {
                        "code": "300750",
                        "name": "宁德时代",
                        "action_status": "ready_for_ai_review",
                        "risk_factors": ["不直接买入"],
                    }
                ],
                "next_action": "研报已完成，可进入组合攻防决策",
            },
            "last_strategy_decision": {
                "ok": True,
                "status": "skipped_notify_unconfigured",
                "report_source": "last_ai_report",
                "candidate_count": 1,
                "reviewed_codes": ["300750"],
                "reviewed_symbols": [
                    {
                        "code": "300750",
                        "name": "宁德时代",
                        "action_status": "ready_for_ai_review",
                        "next_step": "等待通知配置后生成 OMS 工单",
                    }
                ],
                "candidate_guard_summary": {
                    "direct_buy_blocked_count": 1,
                    "message": "以下候选仅可复核或观察，禁止直接买入",
                    "candidates": [
                        {
                            "code": "300750",
                            "name": "宁德时代",
                            "reason": "候选标签未成熟，禁止直接买入",
                            "action_status": "ready_for_ai_review",
                            "trade_readiness": "research_only",
                            "new_buy_allowed": False,
                            "label_ready": False,
                            "risk_factors": ["最新候选的未来窗口标签尚未成熟"],
                        }
                    ],
                },
                "next_action": "补充 Telegram 配置后可发送攻防工单",
            },
        }
    )
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "候选扫描完成。"}],
            [],
        ]
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_empty_synthesis",
        user_text="用 workflow 选出好股票",
        workflow_context=route_workflow("用 workflow 选出好股票"),
        workflow_script={"tasks": [{"id": "scan", "title": "扫描候选", "prompt": "扫描候选"}]},
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 选出好股票"}]))

    try:
        final_text = events[-1]["text"]
        assert "动态 workflow 已完成" in final_text
        assert "候选结论: 受限复核候选 300750 宁德时代" in final_text
        assert "状态=ready_for_ai_review" in final_text
        assert "交易就绪=research_only" in final_text
        assert "不允许新增买入" in final_text
        assert "证据=候选影子S/92" in final_text
        assert "护栏=候选标签未成熟，禁止直接买入" in final_text
        assert "下一步=等待通知配置后生成 OMS 工单" in final_text
        assert "候选扫描完成" in final_text
        assert "300750 宁德时代" in final_text
        assert "候选影子S/92" in final_text
        assert "下一步: 生成 AI 研报" in final_text
        assert "AI研报: reviewed=1, model=gpt-test, next=研报已完成，可进入组合攻防决策" in final_text
        assert "攻防决策: status=skipped_notify_unconfigured, source=last_ai_report" in final_text
        assert "候选护栏: 1只禁止直接买入" in final_text
        assert "候选标签未成熟，禁止直接买入" in final_text
        assert "等待通知配置后生成 OMS 工单" in final_text
    finally:
        _reset_local_db(local_db)


def test_workflow_fallback_labels_watch_only_quality_gate_candidate():
    reason = "000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00"
    summary = _fallback_summary(
        [
            {
                "step": {"title": "扫描候选"},
                "result": {
                    "status": "completed",
                    "result": "候选扫描完成。",
                    "handoff_state": {
                        "last_screen_result": {
                            "selection_brief": {
                                "status": "watch_only",
                                "primary_pick": {
                                    "code": "000013",
                                    "name": "低质量候选",
                                    "action_status": "watch_only",
                                    "risk_adjusted_quality_score": 65.0,
                                    "next_step": "观察池跟踪，暂不进入本轮AI复核",
                                },
                            },
                            "quality_gate": {"status": "blocked_by_quality_gate", "reason": reason},
                            "watch_candidates": [{"code": "000013", "name": "低质量候选"}],
                        }
                    },
                },
            }
        ]
    )

    assert "候选结论: 观察候选 000013 低质量候选" in summary
    assert "首选 000013 低质量候选" not in summary
    assert f"护栏={reason}" in summary
    assert "下一步=观察池跟踪，暂不进入本轮AI复核" in summary


def test_workflow_handoff_and_fallback_prioritize_report_candidates_over_watch():
    tools = StubToolRegistry()
    tools._tool_context = SimpleNamespace(
        state={
            "last_screen_result": {
                "summary": {"report_candidates": 1, "watch_candidates": 1},
                "selection_brief": {
                    "status": "ready_for_ai_review",
                    "primary_pick": {"code": "000013", "name": "观察候选", "action_status": "watch_only"},
                    "best_candidates": [{"code": "000013", "name": "观察候选", "action_status": "watch_only"}],
                },
                "symbols_for_report": [],
                "report_candidates": [
                    {
                        "code": "000014",
                        "name": "高质量候选",
                        "action_status": "ready_for_ai_review",
                        "candidate_shadow_grade": "S",
                        "candidate_shadow_score": 92.0,
                        "next_step": "生成 AI 研报",
                    }
                ],
                "watch_candidates": [{"code": "000013", "name": "观察候选", "action_status": "watch_only"}],
            }
        }
    )

    handoff = _workflow_handoff_state(tools)
    summary = _fallback_summary(
        [
            {
                "step": {"title": "扫描候选"},
                "result": {"status": "completed", "result": "扫描完成。", "handoff_state": handoff},
            }
        ]
    )

    screen = handoff["last_screen_result"]
    assert screen["report_candidates"][0]["code"] == "000014"
    assert screen["watch_candidates"][0]["code"] == "000013"
    assert "候选结论: 首选 000014 高质量候选" in summary
    assert "候选影子S/92" in summary
    assert "观察候选 000013 观察候选" not in summary.splitlines()[1]


def test_workflow_candidate_conclusion_prefers_ready_high_score_over_first_watch():
    summary = _fallback_summary(
        [
            {
                "step": {"title": "扫描候选"},
                "result": {
                    "status": "completed",
                    "result": "扫描完成。",
                    "handoff_state": {
                        "last_screen_result": {
                            "report_candidates": [
                                {
                                    "code": "000013",
                                    "name": "观察候选",
                                    "action_status": "watch_only",
                                    "candidate_shadow_score": 96.0,
                                },
                                {
                                    "code": "000014",
                                    "name": "高质量候选",
                                    "action_status": "ready_for_ai_review",
                                    "candidate_shadow_score": 92.0,
                                    "candidate_shadow_grade": "S",
                                },
                            ]
                        }
                    },
                },
            }
        ]
    )

    assert "候选结论: 首选 000014 高质量候选" in summary
    assert "候选影子S/92" in summary
    assert "观察候选 000013 观察候选" not in summary.splitlines()[1]


def test_workflow_candidate_conclusion_prefers_higher_quality_within_same_status():
    conclusion = _candidate_conclusion_from_handoff(
        {
            "last_screen_result": {
                "report_candidates": [
                    {
                        "code": "000011",
                        "name": "低分候选",
                        "action_status": "ready_for_ai_review",
                        "candidate_shadow_score": 72.0,
                    },
                    {
                        "code": "000012",
                        "name": "高分候选",
                        "action_status": "ready_for_ai_review",
                        "candidate_shadow_score": 91.0,
                    },
                ]
            }
        }
    )

    assert conclusion["code"] == "000012"
    assert "候选结论: 首选 000012 高分候选" in conclusion["line"]
    assert conclusion["evidence"] == ["候选影子91"]


def test_workflow_fallback_handoff_lines_keep_each_stage_when_truncated():
    handoff = {
        "last_screen_result": {
            "selection_brief": {
                "headline": "候选池已形成",
                "best_candidates": [
                    {"code": "300750", "name": "宁德时代", "action_status": "ready_for_ai_review"},
                    {"code": "000001", "name": "平安银行", "action_status": "watch_only"},
                    {"code": "000002", "name": "万科A", "action_status": "watch_only"},
                ],
            }
        },
        "last_recommendation_event_eval": {
            "result_summary": "推荐评估完成\n样本仍需继续观察",
            "summary": {
                "all": {"rows_ready": 12, "rows_total": 20, "hit_rate_pct": 60},
                "ranking_decision": {
                    "status": "candidate",
                    "recommended_strategy": "candidate_shadow_then_score",
                    "recommended_top_k": 1,
                },
            },
            "policy_selection": {
                "selection_strategy": "candidate_shadow_then_score",
                "recommend_date": "2026-06-30",
                "picks": [
                    {
                        "code": "300750",
                        "name": "宁德时代",
                        "label_ready": False,
                        "next_step": "生成 AI 研报",
                    }
                ],
            },
            "candidate_guard_summary": {
                "direct_buy_blocked_count": 1,
                "message": "以下候选仅可复核或观察，禁止直接买入",
                "candidates": [
                    {
                        "code": "300750",
                        "name": "宁德时代",
                        "reason": "候选标签未成熟，禁止直接买入",
                        "label_ready": False,
                    }
                ],
            },
        },
        "last_ai_report": {
            "model": "gpt-test",
            "stock_count": 1,
            "reviewed_symbols": [
                {"code": "300750", "name": "宁德时代", "risk_factors": ["不直接买入"]},
                {"code": "000001", "name": "平安银行", "risk_factors": ["观察"]},
            ],
            "next_action": "研报完成，进入攻防决策",
        },
        "last_strategy_decision": {
            "status": "skipped_notify_unconfigured",
            "report_source": "last_ai_report",
            "candidate_count": 1,
            "reviewed_symbols": [{"code": "300750", "name": "宁德时代", "next_step": "等待通知配置后生成 OMS 工单"}],
            "next_action": "补充 Telegram 配置后可发送攻防工单",
        },
    }

    lines = _fallback_handoff_lines(handoff)

    assert len(lines) == 8
    assert lines[0] == "候选池已形成"
    assert "推荐评估完成" in lines
    assert any("候选护栏: 1只禁止直接买入" in line for line in lines)
    assert any(line.startswith("AI研报:") for line in lines)
    assert any(line.startswith("攻防决策:") for line in lines)
    assert any("补充 Telegram 配置后可发送攻防工单" in line for line in lines)


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
            return [
                {
                    "task_id": "bg_screen",
                    "tool_name": "screen_stocks",
                    "status": "completed",
                    "result_summary": "本轮首选可进入 AI 研报复核: 300750 宁德时代",
                }
            ]

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
        assert "screen_stocks: 本轮首选可进入 AI 研报复核: 300750 宁德时代" in done_event["step"]["summary"]
        assert events[-1]["text"] == "已等待后台筛选并汇总候选。"
    finally:
        _reset_local_db(local_db)


def test_workflow_fallback_summary_includes_completed_background_result_summary():
    summary = _fallback_summary(
        [
            {
                "step": {"title": "扫描候选"},
                "result": {
                    "status": "completed",
                    "result": "筛选已提交后台。",
                    "background_tasks": [
                        {
                            "task_id": "bg_screen",
                            "tool_name": "screen_stocks",
                            "status": "completed",
                            "result_summary": "本轮首选可进入 AI 研报复核: 300750 宁德时代",
                        }
                    ],
                },
            }
        ]
    )

    assert "扫描候选 [completed]: 筛选已提交后台。" in summary
    assert "后台: screen_stocks [completed]: 本轮首选可进入 AI 研报复核: 300750 宁德时代" in summary


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
        assert events[0]["plan"]["steps"][0]["tool_scope"] == ["portfolio"]
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


def test_workflow_executor_retries_read_positions_task_until_portfolio_runs(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-read-positions-expectation.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "我先口头整理持仓。"}],
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "view"}}]}],
            [{"type": "text_delta", "text": "持仓工具已读取。"}],
            [{"type": "text_delta", "text": "已汇总持仓结果。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "portfolio", "description": "Mock portfolio", "parameters": {"type": "object"}},
        ],
        tool_results={"portfolio": {"positions": []}},
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_read_positions_expectation",
        user_text="用 workflow 读取真实持仓",
        workflow_context=route_workflow("用 workflow 读取真实持仓"),
        workflow_script={
            "tasks": [{"id": "positions", "title": "读取真实持仓", "tools": ["portfolio"], "prompt": "读取真实持仓"}]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 读取真实持仓"}]))

    try:
        detail = next(event for event in events if event["type"] == "workflow_step_done")["source"]["agent_detail"]
        assert detail["tool_scope"] == ["portfolio"]
        assert detail["tool_calls"] == ["portfolio"]
        assert [call["name"] for call in tools.calls] == ["portfolio"]
        assert events[-1]["text"] == "已汇总持仓结果。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_retries_scoped_report_task_until_tool_runs(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-report-expectation.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "我先口头整理研报。"}],
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_report", "name": "generate_ai_report", "args": {}}]}],
            [{"type": "text_delta", "text": "研报工具已完成。"}],
            [{"type": "text_delta", "text": "已汇总研报结果。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "generate_ai_report", "description": "Mock report", "parameters": {"type": "object"}},
        ],
        tool_results={"generate_ai_report": {"reviewed_codes": ["300750"]}},
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_report_expectation",
        user_text="用 workflow 生成研报",
        workflow_context=route_workflow("用 workflow 生成研报"),
        workflow_script={
            "tasks": [{"id": "report", "title": "生成研报", "tools": ["generate_ai_report"], "prompt": "生成研报"}]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 生成研报"}]))

    try:
        detail = next(event for event in events if event["type"] == "workflow_step_done")["source"]["agent_detail"]
        assert detail["tool_scope"] == ["generate_ai_report"]
        assert detail["tool_calls"] == ["generate_ai_report"]
        assert [call["name"] for call in tools.calls] == ["generate_ai_report"]
        assert events[-1]["text"] == "已汇总研报结果。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_retries_market_scope_until_tool_runs(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-market-expectation.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "我先口头判断市场环境。"}],
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_market", "name": "get_market_overview", "args": {}}]}],
            [{"type": "text_delta", "text": "市场工具已读取。"}],
            [{"type": "text_delta", "text": "已汇总市场环境。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "get_market_overview", "description": "Mock market", "parameters": {"type": "object"}},
        ],
        tool_results={"get_market_overview": {"status": "ok"}},
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_market_expectation",
        user_text="用 workflow 读取市场环境",
        workflow_context=route_workflow("用 workflow 读取市场环境"),
        workflow_script={
            "tasks": [
                {
                    "id": "market",
                    "title": "读取市场环境",
                    "tools": ["get_market_overview"],
                    "prompt": "读取市场环境",
                }
            ]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 读取市场环境"}]))

    try:
        detail = next(event for event in events if event["type"] == "workflow_step_done")["source"]["agent_detail"]
        assert detail["tool_scope"] == ["get_market_overview"]
        assert detail["tool_calls"] == ["get_market_overview"]
        assert [call["name"] for call in tools.calls] == ["get_market_overview"]
        assert events[-1]["text"] == "已汇总市场环境。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_retries_backtest_scope_until_tool_runs(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-backtest-expectation.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "我先口头整理回测口径。"}],
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_backtest", "name": "run_backtest", "args": {}}]}],
            [{"type": "text_delta", "text": "回测工具已执行。"}],
            [{"type": "text_delta", "text": "已汇总回测结果。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "run_backtest", "description": "Mock backtest", "parameters": {"type": "object"}},
        ],
        tool_results={"run_backtest": {"status": "ok"}},
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_backtest_expectation",
        user_text="用 workflow 跑策略回测",
        workflow_context=route_workflow("用 workflow 跑策略回测"),
        workflow_script={
            "tasks": [{"id": "backtest", "title": "跑策略回测", "tools": ["run_backtest"], "prompt": "跑策略回测"}]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 跑策略回测"}]))

    try:
        detail = next(event for event in events if event["type"] == "workflow_step_done")["source"]["agent_detail"]
        assert detail["tool_scope"] == ["run_backtest"]
        assert detail["tool_calls"] == ["run_backtest"]
        assert [call["name"] for call in tools.calls] == ["run_backtest"]
        assert events[-1]["text"] == "已汇总回测结果。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_does_not_widen_filtered_explicit_tool_scope(tmp_path, monkeypatch):
    from integrations import local_db

    def _blocked_round(messages, tools, _system_prompt):
        assert tools == []
        return [
            {
                "type": "tool_calls",
                "tool_calls": [{"id": "tc_exec", "name": "exec_command", "args": {"command": "pwd"}}],
            }
        ]

    def _after_block_round(messages, tools, _system_prompt):
        assert tools == []
        assert any(
            message.get("role") == "tool" and "不在当前 workflow 允许范围内" in message.get("content", "")
            for message in messages
        )
        return [{"type": "text_delta", "text": "已阻止越权工具。"}]

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-filtered-scope.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            _blocked_round,
            _after_block_round,
            [{"type": "text_delta", "text": "越权工具已被 workflow 边界拦截。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=[
            {"name": "exec_command", "description": "Mock command", "parameters": {"type": "object"}},
            {"name": "screen_stocks", "description": "Mock screen", "parameters": {"type": "object"}},
        ],
        tool_results={"exec_command": {"status": "should_not_run"}},
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_filtered_scope",
        user_text="用 workflow 跑本地命令",
        workflow_context=route_workflow("用 workflow 跑本地命令"),
        workflow_script={
            "tasks": [{"id": "local", "title": "本地命令", "tools": ["exec_command"], "prompt": "尝试运行命令"}]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 跑本地命令"}]))

    try:
        detail = next(event for event in events if event["type"] == "workflow_step_done")["source"]["agent_detail"]
        assert events[0]["plan"]["steps"][0]["tool_scope"] == ["exec_command"]
        assert detail["tool_scope"] == ["exec_command"]
        assert detail["result"] == "已阻止越权工具。"
        assert tools.calls == []
        assert events[-1]["text"] == "越权工具已被 workflow 边界拦截。"
    finally:
        _reset_local_db(local_db)


def test_workflow_portfolio_scope_blocks_question_before_reading_positions(tmp_path, monkeypatch):
    from integrations import local_db

    def _portfolio_round(messages, tools, _system_prompt):
        assert {schema["name"] for schema in tools} == {"portfolio", "ask_user_question"}
        ask_result = next(m for m in messages if m.get("role") == "tool" and m.get("name") == "ask_user_question")
        assert "先不要向用户提问" in ask_result["content"]
        return [
            {
                "type": "tool_calls",
                "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "view"}}],
            }
        ]

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-portfolio-question.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
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
                }
            ],
            _portfolio_round,
            [{"type": "text_delta", "text": "已读取持仓。"}],
            [{"type": "text_delta", "text": "持仓摘要完成。"}],
        ]
    )
    schemas = [
        {"name": "portfolio", "description": "Mock portfolio tool", "parameters": {"type": "object"}},
        {"name": "ask_user_question", "description": "Mock ask tool", "parameters": {"type": "object"}},
    ]
    tools = StubToolRegistry(schemas=schemas, tool_results={"portfolio": {"positions": []}})
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_portfolio_question",
        user_text="你看我持仓呀",
        workflow_context=route_workflow("用 workflow 复核持仓"),
        workflow_script={
            "tasks": [
                {
                    "id": "read_positions",
                    "title": "读取持仓",
                    "tools": ["portfolio", "ask_user_question"],
                    "prompt": "查看持仓并输出摘要",
                }
            ]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "你看我持仓呀"}]))

    try:
        done_event = next(event for event in events if event["type"] == "workflow_step_done")
        detail = done_event["source"]["agent_detail"]
        assert detail["tool_calls"] == ["portfolio"]
        assert [call["name"] for call in tools.calls] == ["portfolio"]
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


def test_workflow_executor_respects_task_dependencies_across_phases(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-cross-phase.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "text_delta", "text": "扫描完成，候选 A。"}],
            [{"type": "text_delta", "text": "研报完成，确认候选 A。"}],
            [{"type": "text_delta", "text": "攻防计划完成。"}],
            [{"type": "text_delta", "text": "跨阶段依赖复核完成。"}],
        ]
    )
    executor = WorkflowExecutor(
        provider,
        StubToolRegistry(),
        session_id="s_cross_phase_dep",
        user_text="按依赖完成选股研报和攻防计划",
        workflow_context=route_workflow("用 workflow 完成选股研报和攻防计划"),
        workflow_script={
            "title": "跨阶段依赖复核",
            "phases": [
                {
                    "id": "decision",
                    "tasks": [
                        {
                            "id": "decision",
                            "title": "形成攻防",
                            "depends_on": ["report"],
                            "prompt": "基于研报输出攻防边界",
                        }
                    ],
                },
                {
                    "id": "report",
                    "tasks": [
                        {
                            "id": "report",
                            "title": "生成研报",
                            "depends_on": ["scan"],
                            "prompt": "基于候选生成研报",
                        }
                    ],
                },
                {
                    "id": "scan",
                    "tasks": [{"id": "scan", "title": "扫描候选", "prompt": "先扫描候选"}],
                },
            ],
            "synthesis_prompt": "按依赖顺序汇总。",
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "按依赖完成选股研报和攻防计划"}]))

    try:
        step_starts = [event for event in events if event["type"] == "workflow_step_start"]
        step_dones = [event for event in events if event["type"] == "workflow_step_done"]
        phase_starts = [event for event in events if event["type"] == "workflow_phase_start"]
        assert [event["step"]["step_id"] for event in step_starts] == ["scan", "report", "decision"]
        assert [event["phase"] for event in phase_starts] == ["scan", "report", "decision"]
        assert events.index(step_dones[0]) < events.index(step_starts[1])
        assert events.index(step_dones[1]) < events.index(step_starts[2])
        assert "扫描完成，候选 A。" in provider.calls[1]["messages"][0]["content"]
        assert "研报完成，确认候选 A。" in provider.calls[2]["messages"][0]["content"]
        assert events[-1]["text"] == "跨阶段依赖复核完成。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_serializes_inferred_stock_selection_dependencies(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-inferred-deps.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_scan", "name": "screen_stocks", "args": {}}]}],
            [{"type": "text_delta", "text": "候选扫描完成。"}],
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_report", "name": "generate_ai_report", "args": {}}]}],
            [{"type": "text_delta", "text": "研报生成完成。"}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_decision", "name": "generate_strategy_decision", "args": {}}],
                }
            ],
            [{"type": "text_delta", "text": "攻防计划完成。"}],
            [{"type": "text_delta", "text": "选股链路完成。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=deepcopy(TOOL_SCHEMAS),
        tool_results={
            "screen_stocks": {"selection_brief": {"best_codes": ["300750"]}},
            "generate_ai_report": {"reviewed_codes": ["300750"]},
            "generate_strategy_decision": {"reviewed_codes": ["300750"], "status": "completed"},
        },
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_inferred_deps",
        user_text="用 workflow 做选股、研报和攻防计划",
        workflow_context=route_workflow("用 workflow 做选股、研报和攻防计划"),
        workflow_script={
            "tasks": [
                {"id": "scan", "title": "扫描候选", "tools": ["screen_stocks"], "prompt": "扫描今日候选。"},
                {"id": "report", "title": "生成研报", "tools": ["generate_ai_report"], "prompt": "基于候选生成研报。"},
                {
                    "id": "decision",
                    "title": "形成攻防",
                    "tools": ["generate_strategy_decision"],
                    "prompt": "基于候选和研报输出攻防边界。",
                },
            ]
        },
    )

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 做选股、研报和攻防计划"}]))

    try:
        starts = [event for event in events if event["type"] == "workflow_step_start"]
        dones = [event for event in events if event["type"] == "workflow_step_done"]
        assert [event["step"]["step_id"] for event in starts] == ["scan", "report", "decision"]
        assert starts[1]["step"]["depends_on"] == ["scan"]
        assert starts[2]["step"]["depends_on"] == ["report"]
        assert events.index(dones[0]) < events.index(starts[1])
        assert events.index(dones[1]) < events.index(starts[2])
        assert [call["name"] for call in tools.calls] == [
            "screen_stocks",
            "generate_ai_report",
            "generate_strategy_decision",
        ]
        assert events[-1]["text"] == "选股链路完成。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_topologically_runs_out_of_order_stock_selection_tools(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-out-of-order-stock-deps.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_scan", "name": "screen_stocks", "args": {}}]}],
            [{"type": "text_delta", "text": "候选扫描完成。"}],
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_report", "name": "generate_ai_report", "args": {}}]}],
            [{"type": "text_delta", "text": "研报生成完成。"}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_decision", "name": "generate_strategy_decision", "args": {}}],
                }
            ],
            [{"type": "text_delta", "text": "攻防计划完成。"}],
            [{"type": "text_delta", "text": "乱序选股链路完成。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=deepcopy(TOOL_SCHEMAS),
        tool_results={
            "screen_stocks": {"selection_brief": {"best_codes": ["300750"]}},
            "generate_ai_report": {"reviewed_codes": ["300750"]},
            "generate_strategy_decision": {"reviewed_codes": ["300750"], "status": "completed"},
        },
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_out_of_order_stock_deps",
        user_text="用 workflow 做选股、研报和攻防计划",
        workflow_context=route_workflow("用 workflow 做选股、研报和攻防计划"),
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

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 做选股、研报和攻防计划"}]))

    try:
        starts = [event for event in events if event["type"] == "workflow_step_start"]
        assert [event["step"]["step_id"] for event in starts] == ["scan", "report", "decision"]
        assert starts[0]["step"]["depends_on"] == []
        assert starts[1]["step"]["depends_on"] == ["scan"]
        assert starts[2]["step"]["depends_on"] == ["report"]
        assert [call["name"] for call in tools.calls] == [
            "screen_stocks",
            "generate_ai_report",
            "generate_strategy_decision",
        ]
        assert events[-1]["text"] == "乱序选股链路完成。"
    finally:
        _reset_local_db(local_db)


def test_workflow_executor_topologically_runs_cross_phase_stock_selection_tools(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow-cross-phase-stock-deps.db")
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    provider = ScriptedProvider(
        rounds=[
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_scan", "name": "screen_stocks", "args": {}}]}],
            [{"type": "text_delta", "text": "候选扫描完成。"}],
            [{"type": "tool_calls", "tool_calls": [{"id": "tc_report", "name": "generate_ai_report", "args": {}}]}],
            [{"type": "text_delta", "text": "研报生成完成。"}],
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_decision", "name": "generate_strategy_decision", "args": {}}],
                }
            ],
            [{"type": "text_delta", "text": "攻防计划完成。"}],
            [{"type": "text_delta", "text": "跨阶段乱序选股链路完成。"}],
        ]
    )
    tools = StubToolRegistry(
        schemas=deepcopy(TOOL_SCHEMAS),
        tool_results={
            "screen_stocks": {"selection_brief": {"best_codes": ["300750"]}},
            "generate_ai_report": {"reviewed_codes": ["300750"]},
            "generate_strategy_decision": {"reviewed_codes": ["300750"], "status": "completed"},
        },
    )
    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s_cross_phase_stock_deps",
        user_text="用 workflow 做选股、研报和攻防计划",
        workflow_context=route_workflow("用 workflow 做选股、研报和攻防计划"),
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

    events = list(executor.run_stream([{"role": "user", "content": "用 workflow 做选股、研报和攻防计划"}]))

    try:
        starts = [event for event in events if event["type"] == "workflow_step_start"]
        assert [event["step"]["step_id"] for event in starts] == ["scan", "report", "decision"]
        assert starts[0]["step"]["depends_on"] == []
        assert starts[1]["step"]["depends_on"] == ["scan"]
        assert starts[2]["step"]["depends_on"] == ["report"]
        assert [call["name"] for call in tools.calls] == [
            "screen_stocks",
            "generate_ai_report",
            "generate_strategy_decision",
        ]
        assert events[-1]["text"] == "跨阶段乱序选股链路完成。"
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


def test_phase_batches_orders_cross_phase_dependencies_globally():
    decision = WorkflowStep(step_id="decision", title="形成攻防", phase="decision", depends_on=("report",))
    report = WorkflowStep(step_id="report", title="生成研报", phase="report", depends_on=("scan",))
    scan = WorkflowStep(step_id="scan", title="扫描候选", phase="scan")

    assert [[step.step_id for step in batch] for batch in _phase_batches([decision, report, scan])] == [
        ["scan"],
        ["report"],
        ["decision"],
    ]


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
