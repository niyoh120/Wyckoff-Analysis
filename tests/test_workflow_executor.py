from __future__ import annotations

from cli.workflows.executor import WorkflowExecutor
from cli.workflows.resume import build_resume_prompt
from cli.workflows.store import get_workflow_run, load_workflow_events
from tests.helpers.agent_loop_harness import ScriptedProvider, StubToolRegistry


def _reset_local_db(local_db) -> None:
    if local_db._conn is not None:
        local_db._conn.close()
    local_db._conn = None


def test_workflow_executor_persists_plan_and_steps(tmp_path, monkeypatch):
    from integrations import local_db

    _reset_local_db(local_db)
    monkeypatch.setattr("core.constants.LOCAL_DB_PATH", tmp_path / "workflow.db")
    provider = ScriptedProvider(
        rounds=[
            [
                {
                    "type": "tool_calls",
                    "tool_calls": [{"id": "tc_pf", "name": "portfolio", "args": {"mode": "view"}}],
                    "text": "",
                }
            ],
            [{"type": "text_delta", "text": "持仓复盘完成。"}],
        ]
    )
    tools = StubToolRegistry(tool_results={"portfolio": {"positions": []}})

    executor = WorkflowExecutor(
        provider,
        tools,
        session_id="s1",
        user_text="我的持仓怎么样",
    )
    events = list(executor.run_stream([{"role": "user", "content": "我的持仓怎么样"}]))

    run = get_workflow_run(executor.run.run_id)
    stored_events = load_workflow_events(executor.run.run_id)
    try:
        assert events[0]["type"] == "workflow_plan"
        assert any(event["type"] == "workflow_step_start" for event in events)
        assert any(event["type"] == "workflow_done" for event in events)
        assert run and run["status"] == "completed"
        assert run["workflow"] == "portfolio_review"
        assert stored_events[0]["event_type"] == "workflow_plan"
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
