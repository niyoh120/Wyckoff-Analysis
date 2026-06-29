from __future__ import annotations

import json

from cli.workflows.control import WorkflowControl
from cli.workflows.executor import WorkflowExecutor
from cli.workflows.resume import build_resume_prompt
from cli.workflows.router import route_workflow
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


def _reset_local_db(local_db) -> None:
    if local_db._conn is not None:
        local_db._conn.close()
    local_db._conn = None


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
        assert events[0]["route"]["reason"] == "用户显式要求动态 workflow"
        assert events[0]["plan"]["route"]["matches"] == ["用 workflow"]
        assert events[0]["plan"]["script"]["title"] == "持仓复盘"
        assert events[0]["plan"]["steps"][0]["agent"] == "analysis"
        assert any(event["type"] == "workflow_step_start" for event in events)
        assert any(event["type"] == "workflow_done" for event in events)
        assert events[-1]["type"] == "done"
        assert events[-1]["text"] == "持仓复盘完成。"
        assert "只看核心仓位" in provider.calls[1]["messages"][0]["content"]
        assert "汇总持仓风险和下一步动作" in provider.calls[3]["messages"][0]["content"]
        assert run and run["status"] == "completed"
        assert run["workflow"] == "dynamic_task"
        assert run["plan"]["script"]["runtime"]["script_path"].startswith(str(tmp_path / "workflow-runs"))
        assert (tmp_path / "workflow-runs" / "s1" / f"{executor.run.run_id}.json").is_file()
        assert "错别字" in provider.calls[0]["system_prompt"]
        assert "运行上下文" in provider.calls[0]["messages"][0]["content"]
        assert stored_events[0]["event_type"] == "workflow_plan"
        done_event = next(row for row in stored_events if row["event_type"] == "workflow_step_done")
        detail = done_event["payload"]["source"]["agent_detail"]
        assert detail["step_id"] == "read_positions"
        assert detail["tool_calls"] == ["portfolio"]
        assert "持仓风险低" in detail["result"]
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
