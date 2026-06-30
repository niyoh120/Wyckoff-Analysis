from __future__ import annotations

import json
import threading
import time

from cli.workflows.control import WorkflowControl
from cli.workflows.executor import WorkflowExecutor, _phase_batches
from cli.workflows.models import WorkflowStep
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
    assert "自然语言理解、上下文恢复和任务拆分由你完成" in _PLAN_SYSTEM_PROMPT
    assert "不需要选择内部执行角色" in _PLAN_SYSTEM_PROMPT
    assert "不要填写 agent/role" in _PLAN_SYSTEM_PROMPT
    assert "可用 agent" not in _PLAN_SYSTEM_PROMPT
    assert '"agent": "可选，research|analysis|trading"' not in _PLAN_SYSTEM_PROMPT


def test_workflow_planner_accepts_agent_aliases_and_steps_field():
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

    assert [step.agent for step in run.steps] == ["research", "trading"]
    assert [step.tools for step in run.steps] == [("delegate_to_research",), ("delegate_to_trading",)]
    assert run.steps[1].prompt == "输出观察、买入和失效条件"
    assert run.steps[1].depends_on == ("scan",)
    assert run.script["runtime"]["planner"] == "stored_script"


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
    assert run.steps[0].agent == "analysis"
    assert run.steps[0].phase == "top_level"
    assert run.steps[0].prompt == "诊断 300750 的量价结构"


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
    assert run.steps[0].agent == "task"
    assert run.steps[0].tools == ()
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
        assert events[0]["plan"]["steps"][0]["agent"] == "analysis"
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
        assert "最可能的任务意图" in provider.calls[0]["system_prompt"]
        assert "表达形式本身" in provider.calls[0]["system_prompt"]
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
