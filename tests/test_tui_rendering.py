from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.markdown import Markdown

from cli.tui import (
    _background_task_summary,
    _display_final_response,
    _display_workflow_plan_event,
    _display_workflow_step_event,
    _pending_workflow_reply_intent,
    _pop_lines,
    _replace_streamed_response,
    _settle_markdown_render,
    _workflow_control_intent,
    _workflow_detail_step_line,
    _write_counted,
)


class _FakeLog:
    def __init__(self) -> None:
        self.lines = ["kept"]
        self._widest_line_width = 0
        self.virtual_size = None
        self.refreshed = False
        self.layout_refreshed = False
        self.scrolled = False

    def write(self, renderable) -> None:
        if isinstance(renderable, list):
            self.lines.extend(renderable)
        else:
            self.lines.append(renderable)

    def refresh(self, *, layout: bool = False) -> None:
        self.refreshed = True
        self.layout_refreshed = self.layout_refreshed or layout

    def scroll_end(self, *, animate: bool = False) -> None:
        self.scrolled = True


def test_write_counted_returns_actual_added_strips_for_wrapped_renderable():
    log = _FakeLog()

    added = _write_counted(log, ["wrap line 1", "wrap line 2"])

    assert added == 2
    assert log.lines == ["kept", "wrap line 1", "wrap line 2"]


def test_pop_lines_removes_actual_added_strips():
    log = _FakeLog()
    added = _write_counted(log, ["wrap line 1", "wrap line 2"])

    _pop_lines(log, added)

    assert log.lines == ["kept"]
    assert log.refreshed is True


def test_replace_streamed_response_redraws_markdown():
    log = _FakeLog()
    log.lines.extend(["  ---", "## raw", "| a |"])

    added = _replace_streamed_response(log, 3, "## Rendered\n\n| a |\n| - |")

    assert added == 1
    assert log.lines[0] == "kept"
    assert isinstance(log.lines[1], Markdown)
    assert log.refreshed is True
    assert log.layout_refreshed is True


def test_settle_markdown_render_refreshes_layout_and_scrolls():
    log = _FakeLog()

    _settle_markdown_render(log)

    assert log.layout_refreshed is True
    assert log.scrolled is True


def test_display_final_response_replaces_streamed_raw_text():
    log = _FakeLog()
    log.lines.extend(["  ---", "**raw**"])
    writes = []

    displayed = _display_final_response(
        log,
        "**rendered**",
        streaming_started=True,
        stream_separator_strips=1,
        stream_text_strips=1,
        write=writes.append,
        call_from_thread=lambda func, *args: func(*args),
    )

    assert displayed is True
    assert writes == []
    assert log.lines[0] == "kept"
    assert isinstance(log.lines[1], Markdown)


def test_display_workflow_plan_event_includes_route_reason_without_internal_scope():
    writes = []
    scrolled = []

    run_id, workflow_name = _display_workflow_plan_event(
        {
            "run_id": "wf_1",
            "workflow": "backtest",
            "label": "策略回测",
            "route": {"reason": "检测到策略回测意图", "matches": ["回测"], "confidence": 0.9},
            "plan": {"steps": [{"title": "执行回测任务", "agent": "research", "tool_scope": ["run_backtest"]}]},
        },
        writes.append,
        lambda: scrolled.append(True),
    )

    assert run_id == "wf_1"
    assert workflow_name == "backtest"
    assert "策略回测" in str(writes[0])
    assert "检测到策略回测意图" in str(writes[1])
    assert "命中：回测" in str(writes[1])
    assert "待执行" in str(writes[2])
    assert "工具：run_backtest" not in str(writes[2])
    assert "research" not in str(writes[2])
    assert scrolled == [True]


def test_display_workflow_step_event_hides_internal_scope():
    writes = []
    scrolled = []

    _display_workflow_step_event(
        {
            "step": {
                "title": "读取持仓",
                "agent": "analysis",
                "status": "running",
                "tool_scope": ["portfolio", "analyze_stock"],
                "summary": "analysis: start",
            }
        },
        writes.append,
        lambda: scrolled.append(True),
    )

    rendered = str(writes[0])
    assert "读取持仓" in rendered
    assert "运行中" in rendered
    assert "工具：portfolio, analyze_stock" not in rendered
    assert "analysis:" not in rendered
    assert scrolled == [True]


def test_workflow_detail_step_line_includes_tool_scope():
    line = _workflow_detail_step_line(
        {
            "step_id": "read_positions",
            "title": "读取持仓",
            "agent": "analysis",
            "status": "completed",
            "tool_scope": ["portfolio"],
            "summary": "analysis: completed 1.2s",
        }
    )

    assert "read_positions" in line
    assert "工具：portfolio" in line
    assert "completed" in line
    assert "analysis: completed" in line


def test_workflow_control_intent_requires_explicit_control_action():
    assert _workflow_control_intent("解释一下 workflow 是什么") is None
    assert _workflow_control_intent("查看 workflow wf_abc123") == ("show", "wf_abc123")
    assert _workflow_control_intent("把 workflow wf_abc123 的脚本打开") == ("script", "wf_abc123")
    assert _workflow_control_intent("复跑刚才的 workflow") == ("rerun", "")
    assert _workflow_control_intent("批准 workflow wf_abc123") == ("approve", "wf_abc123")
    assert _workflow_control_intent("暂停 workflow wf_abc123") == ("pause", "wf_abc123")
    assert _workflow_control_intent("停止 workflow wf_abc123") == ("stop", "wf_abc123")


def test_pending_workflow_reply_intent_accepts_chat_style_approval():
    assert _pending_workflow_reply_intent("好") == "approve"
    assert _pending_workflow_reply_intent("开始吧") == "approve"
    assert _pending_workflow_reply_intent("取消") == "deny"
    assert _pending_workflow_reply_intent("解释一下 workflow 是什么") == ""


def test_background_task_summary_uses_tool_result_preview_for_large_screen_result(tmp_path, monkeypatch):
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    result = {
        "ok": True,
        "selection_brief": {
            "status": "ready_for_ai_review",
            "headline": "本轮首选可进入 AI 研报复核: 300750 宁德时代",
            "best_codes": ["300750"],
        },
        "trigger_groups": {"huge": [{"code": f"{idx:06d}", "blob": "x" * 200} for idx in range(80)]},
    }

    summary = _background_task_summary("screen_stocks", "bg_screen", result, max_chars=1000)

    assert "result_ref:" in summary
    assert '"selection_brief": {"status": "ready_for_ai_review"' in summary
    assert "本轮首选可进入 AI 研报复核: 300750 宁德时代" in summary
    assert '"trigger_groups"' not in summary
    stored = list((tmp_path / "tool-results").glob("*.json"))
    assert len(stored) == 1
