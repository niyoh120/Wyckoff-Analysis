from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from rich.markdown import Markdown

from cli.tui import (
    WyckoffTUI,
    _background_task_summary,
    _chatlog_role_for_turn,
    _display_final_response,
    _display_workflow_plan_event,
    _display_workflow_step_event,
    _is_system_notification_message,
    _pending_workflow_reply_intent,
    _pop_lines,
    _replace_streamed_response,
    _settle_markdown_render,
    _system_notification_queue_item,
    _tool_result_view,
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


def test_expand_recent_workflow_followup_uses_current_session(monkeypatch):
    app = object.__new__(WyckoffTUI)
    app._session_id = "s1"
    monkeypatch.setattr(
        "cli.workflows.store.list_workflow_runs",
        lambda limit=8: [
            {
                "run_id": "wf_other",
                "session_id": "s2",
                "label": "其他",
                "status": "running",
                "user_text": "其他任务",
                "plan": {"steps": [{"step_id": "other", "title": "其他"}]},
            },
            {
                "run_id": "wf_current",
                "session_id": "s1",
                "label": "当前",
                "status": "running",
                "user_text": "给我选股",
                "plan": {"steps": [{"step_id": "scan", "title": "扫描候选", "tool_scope": ["screen_stocks"]}]},
            },
        ],
    )

    expanded = app._expand_recent_workflow_followup("接着刚才那个")

    assert "继续 workflow wf_current" in expanded
    assert "wf_other" not in expanded


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


def test_display_workflow_plan_event_keeps_pending_plan_compact():
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
    rendered = "\n".join(str(item) for item in writes)
    assert "策略回测" in str(writes[0])
    assert "1 个动态任务" in str(writes[0])
    assert "识别原因：检测到策略回测意图" in rendered
    assert "命中：回测" in rendered
    assert "置信度：90%" in rendered
    assert "/workflow show wf_1" in rendered
    assert "待执行" not in rendered
    assert "1. 执行回测任务" in rendered
    assert "工具: 回测" in rendered
    assert "research" not in rendered
    assert scrolled == [True]


def test_display_workflow_plan_event_uses_plan_route_for_saved_events():
    writes = []

    _display_workflow_plan_event(
        {
            "run_id": "wf_saved",
            "workflow": "dynamic_task",
            "label": "保存脚本",
            "plan": {
                "route": {"reason": "复用已保存 workflow script", "matches": ["saved"], "confidence": 0.75},
                "script": {"runtime": {"planner": "stored_script"}},
                "steps": [{"title": "读取持仓", "rationale": "复用保存脚本"}],
            },
        },
        writes.append,
        lambda: None,
    )

    rendered = "\n".join(str(item) for item in writes)
    assert "识别原因：复用已保存 workflow script" in rendered
    assert "命中：saved" in rendered
    assert "脚本来源：已保存脚本" in rendered


def test_display_workflow_plan_event_surfaces_trimmed_model_plan():
    writes = []

    _display_workflow_plan_event(
        {
            "run_id": "wf_trimmed",
            "workflow": "dynamic_task",
            "label": "今日选股",
            "plan": {
                "script": {
                    "runtime": {
                        "step_limit": 24,
                        "original_step_count": 27,
                        "truncated_step_count": 3,
                    }
                },
                "steps": [{"title": f"任务 {index}"} for index in range(24)],
            },
        },
        writes.append,
        lambda: None,
    )

    assert "24/27 个动态任务" in str(writes[0])
    assert "已收敛 3 个过长任务" in str(writes[0])


def test_display_workflow_plan_event_surfaces_planner_provenance():
    writes = []

    _display_workflow_plan_event(
        {
            "run_id": "wf_model",
            "workflow": "dynamic_task",
            "label": "今日选股",
            "plan": {
                "script": {"rationale": "模型决定先缩小候选池再做攻防复核", "runtime": {"planner": "model_script"}},
                "steps": [{"title": "扫描候选", "rationale": "先缩小候选池"}],
            },
        },
        writes.append,
        lambda: None,
    )

    rendered = "\n".join(str(item) for item in writes)
    assert "脚本来源：模型生成" in rendered
    assert "模型拆分：模型决定先缩小候选池再做攻防复核" in rendered
    assert "1. 扫描候选" in rendered


def test_display_workflow_plan_event_surfaces_fallback_reason():
    writes = []

    _display_workflow_plan_event(
        {
            "run_id": "wf_fallback",
            "workflow": "dynamic_task",
            "label": "动态任务",
            "plan": {
                "script": {
                    "runtime": {
                        "planner": "fallback_script",
                        "fallback_reason": "provider unavailable",
                    }
                },
                "steps": [{"title": "单步处理", "success_criteria": "给出结论"}],
            },
        },
        writes.append,
        lambda: None,
    )

    rendered = "\n".join(str(item) for item in writes)
    assert "脚本来源：回退单步 · provider unavailable" in rendered
    assert "1. 单步处理" in rendered


def test_display_workflow_plan_event_surfaces_model_step_boundaries():
    writes = []

    _display_workflow_plan_event(
        {
            "run_id": "wf_dynamic",
            "workflow": "dynamic_task",
            "label": "今日选股",
            "plan": {
                "steps": [
                    {
                        "title": "扫描候选",
                        "tool_scope": ["screen_stocks", "get_market_overview"],
                        "rationale": "先缩小候选池",
                        "success_criteria": "输出候选代码和风险状态",
                        "risk_guard": "不写入推荐或持仓",
                    },
                    {
                        "title": "攻防计划",
                        "tool_scope": ["generate_strategy_decision"],
                        "depends_on": ["scan"],
                        "success_criteria": "说明观察、复核和禁止直接买入的边界",
                    },
                ],
            },
        },
        writes.append,
        lambda: None,
    )

    rendered = "\n".join(str(item) for item in writes)
    assert "1. 扫描候选" in rendered
    assert "工具: 全市场扫描、大盘水温" in rendered
    assert "目标: 先缩小候选池" in rendered
    assert "验收: 输出候选代码和风险状态" in rendered
    assert "边界: 不写入推荐或持仓" in rendered
    assert "2. 攻防计划" in rendered
    assert "工具: 攻防决策" in rendered
    assert "依赖: scan" in rendered
    assert "禁止直接买入" in rendered
    assert "/workflow show wf_dynamic" in rendered


def test_display_workflow_plan_event_surfaces_effective_tool_scope():
    writes = []

    _display_workflow_plan_event(
        {
            "run_id": "wf_generic",
            "workflow": "portfolio_review",
            "label": "持仓复盘",
            "plan": {
                "steps": [
                    {
                        "title": "复盘持仓",
                        "tool_scope": [],
                        "effective_tool_scope": ["portfolio", "analyze_stock"],
                        "rationale": "让模型按上下文决定最小工具调用",
                    }
                ],
            },
        },
        writes.append,
        lambda: None,
    )

    rendered = "\n".join(str(item) for item in writes)
    assert "1. 复盘持仓" in rendered
    assert "可用工具: 持仓、个股分析" in rendered
    assert "目标: 让模型按上下文决定最小工具调用" in rendered


def test_display_workflow_plan_event_previews_tool_only_model_steps():
    writes = []

    _display_workflow_plan_event(
        {
            "run_id": "wf_outline",
            "workflow": "dynamic_task",
            "label": "持仓复盘",
            "plan": {
                "steps": [
                    {"title": "读取持仓与资金", "tool_scope": ["portfolio"]},
                    {"title": "诊断持仓与市场环境", "tool_scope": ["portfolio", "get_market_overview"]},
                    {"title": "形成去留和风险动作", "tool_scope": ["generate_strategy_decision"]},
                ],
            },
        },
        writes.append,
        lambda: None,
    )

    rendered = "\n".join(str(item) for item in writes)
    assert "1. 读取持仓与资金" in rendered
    assert "工具: 持仓" in rendered
    assert "2. 诊断持仓与市场环境" in rendered
    assert "工具: 持仓、大盘水温" in rendered
    assert "3. 形成去留和风险动作" in rendered
    assert "工具: 攻防决策" in rendered


def test_submit_workflow_background_auto_starts_model_plan():
    app = object.__new__(WyckoffTUI)
    app._messages = [{"role": "user", "content": "memory\n帮我选出好股票", "_raw_content": "帮我选出好股票"}]
    chatlog_rows = []
    launched = []
    writes = []
    scrolls = []

    class Runtime:
        def __init__(self) -> None:
            self.prepared = False

        def prepare_run(self):
            self.prepared = True
            return {
                "run_id": "wf_auto",
                "workflow": "dynamic_task",
                "label": "今日选股",
                "plan": {
                    "script": {"runtime": {"planner": "model_script"}},
                    "steps": [{"title": "扫描候选", "rationale": "先缩小候选池"}],
                },
            }

    runtime = Runtime()
    app._chatlog_save = lambda role, content, **kwargs: chatlog_rows.append((role, content, kwargs))
    app._launch_workflow_background = lambda *args: launched.append(args)

    started = WyckoffTUI._submit_workflow_background(
        app,
        runtime,
        SimpleNamespace(
            turn_user_index=0,
            user_text="帮我选出好股票",
            model_name="model",
            provider_name="provider",
        ),
        "system prompt",
        writes.append,
        lambda: scrolls.append(True),
    )

    assert started is True
    assert runtime.prepared is True
    assert app._messages[0]["content"] == "帮我选出好股票"
    assert app._messages[-1]["role"] == "assistant"
    assert "自动开始后台运行" in app._messages[-1]["content"]
    assert chatlog_rows[0][0] == "user"
    assert chatlog_rows[1][0] == "assistant"
    assert "workflow_run_id" in chatlog_rows[1][2]["metadata_json"]
    assert len(launched) == 1
    assert launched[0][1] == [{"role": "user", "content": "帮我选出好股票"}]
    assert launched[0][2] == "system prompt"
    assert launched[0][5].startswith("wfbg_wf_auto_")
    rendered = "\n".join(str(item) for item in writes)
    assert "脚本来源：模型生成" in rendered
    assert "/workflow show wf_auto" in rendered
    assert scrolls


def test_complete_workflow_background_does_not_wake_idle_agent():
    app = object.__new__(WyckoffTUI)
    log = _FakeLog()
    chatlog_rows = []
    updates = []
    app.query_one = lambda *_args, **_kwargs: log
    app._busy = False
    app._queue = deque()
    app._messages = []
    app._session_tokens = {"input": 0, "output": 0, "rounds": 0}
    app._update_status = lambda: updates.append(True)
    app._chatlog_save = lambda role, content, **kwargs: chatlog_rows.append((role, content, kwargs))

    WyckoffTUI._complete_workflow_background(
        app,
        "wfbg_idle",
        {
            "workflow_run_id": "wf_idle",
            "workflow": "dynamic_task",
            "final_text": "候选结论: 首选 300750 宁德时代",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    )

    assert app._queue == deque()
    assert app._messages[-1]["content"] == "候选结论: 首选 300750 宁德时代"
    assert app._session_tokens == {"input": 10, "output": 5, "rounds": 1}
    assert chatlog_rows[0][0] == "assistant"
    assert updates == [True]
    assert "workflow 后台完成" in str(log.lines[-2])


def test_complete_workflow_background_queues_system_notification_when_busy():
    app = object.__new__(WyckoffTUI)
    log = _FakeLog()
    app.query_one = lambda *_args, **_kwargs: log
    app._busy = True
    app._queue = deque()
    app._messages = []
    app._session_tokens = {"input": 0, "output": 0, "rounds": 0}
    app._update_status = lambda: None
    app._chatlog_save = lambda *_args, **_kwargs: None

    WyckoffTUI._complete_workflow_background(
        app,
        "wfbg_busy",
        {
            "workflow_run_id": "wf_busy",
            "workflow": "dynamic_task",
            "final_text": "候选结论: 首选 300750 宁德时代\n风险边界: 跌破 20 日线转观察",
            "events": [{"type": "workflow_step_done", "step": {"title": "扫描候选", "status": "completed"}}],
        },
    )

    assert len(app._queue) == 1
    item = app._queue[0]
    assert item["type"] == "system_notification"
    assert "<run-id>wf_busy</run-id>" in item["content"]
    assert "dynamic-workflow event" in item["content"]
    assert "候选结论: 首选 300750 宁德时代" in item["content"]
    assert app._messages[-1]["role"] == "assistant"


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
    assert "工具: 持仓、个股分析" in rendered
    assert "工具：portfolio, analyze_stock" not in rendered
    assert "analysis:" not in rendered
    assert scrolled == [True]


def test_display_workflow_step_event_shows_effective_tool_scope():
    writes = []

    _display_workflow_step_event(
        {
            "step": {
                "title": "复盘持仓",
                "agent": "task",
                "status": "running",
                "tool_scope": [],
                "effective_tool_scope": ["portfolio", "analyze_stock"],
            }
        },
        writes.append,
        lambda: None,
    )

    rendered = str(writes[0])
    assert "复盘持仓" in rendered
    assert "可用工具: 持仓、个股分析" in rendered
    assert "task" not in rendered


def test_tool_result_view_surfaces_screen_candidate_risk():
    summary, renderable = _tool_result_view(
        {
            "type": "tool_result",
            "name": "screen_stocks",
            "elapsed_ms": 1200,
            "result": {
                "selection_brief": {
                    "headline": "本轮首选可进入 AI 研报复核: 300750 宁德时代",
                    "primary_pick": {
                        "code": "300750",
                        "name": "宁德时代",
                        "priority_score": 12.5,
                        "shadow_score": 4.2,
                        "quality_factors": ["高优先级研报候选", "趋势线"],
                        "risk_factors": ["大盘风险闸门关闭"],
                        "action_status": "blocked_by_market_gate",
                        "next_step": "只观察",
                    },
                }
            },
        },
        None,
    )

    rendered = str(renderable)
    assert summary["brief"] == [
        "本轮首选可进入 AI 研报复核: 300750 宁德时代",
        "候选结论: 阻断候选 300750 宁德时代 · 风险闸门关闭 · 证据: 优先分12.5；动态分4.2 · 亮点: 高优先级研报候选；趋势线 · 风险: 大盘风险闸门关闭 · 下一步: 只观察",
    ]
    assert "screen_stocks" in rendered
    assert "候选结论: 阻断候选 300750 宁德时代" in rendered
    assert "优先分12.5" in rendered
    assert "动态分4.2" in rendered
    assert "高优先级研报候选" in rendered
    assert "风险闸门关闭" in rendered
    assert "大盘风险闸门关闭" in rendered


def test_tool_result_view_surfaces_recommendation_eval_pick_action():
    summary, renderable = _tool_result_view(
        {
            "type": "tool_result",
            "name": "evaluate_recommendation_events",
            "elapsed_ms": 1200,
            "result": {
                "result_summary": (
                    "推荐事件评估: ready=12/20, hit=60%, ranking_decision=candidate\n"
                    "排序接入候选: candidate_shadow_then_score top1 已通过样本/lift/风险门槛\n"
                    "最新候选(20260601, candidate_shadow_then_score): 300750 宁德时代"
                ),
                "policy_selection": {
                    "picks": [
                        {
                            "code": "300750",
                            "name": "宁德时代",
                            "funnel_score": 89.5,
                            "candidate_shadow_score": 92.0,
                            "candidate_shadow_grade": "S",
                            "entry_quality_score": 84.0,
                            "entry_quality_grade": "A",
                            "candidate_quality_score": 92.0,
                            "risk_adjusted_quality_score": 87.0,
                            "entry_risk_penalty": 5.0,
                            "action_status": "ready_for_ai_review",
                            "quality_factors": ["候选影子评级 S"],
                            "risk_factors": ["最新候选的未来窗口标签尚未成熟"],
                            "next_step": "生成 AI 研报并结合持仓形成攻防决策",
                        }
                    ]
                },
            },
        },
        None,
    )

    rendered = str(renderable)
    assert summary["brief"][-1].startswith("候选结论: 首选 300750 宁德时代 · 可进入AI复核")
    assert "候选结论: 首选 300750 宁德时代" in rendered
    assert "漏斗分89.5" in rendered
    assert "候选影子S/92" in rendered
    assert "入场A/84" in rendered
    assert "风险调整分87" in rendered
    assert "候选影子评级 S" in rendered
    assert "最新候选的未来窗口标签尚未成熟" in rendered


def test_workflow_detail_step_line_includes_tool_scope():
    line = _workflow_detail_step_line(
        {
            "step_id": "read_positions",
            "title": "读取持仓",
            "agent": "analysis",
            "status": "completed",
            "tool_scope": ["portfolio"],
            "depends_on": ["market"],
            "rationale": "先确认真实仓位",
            "success_criteria": "输出持仓风险",
            "risk_guard": "不写入交易",
            "summary": "analysis: completed 1.2s",
        }
    )

    assert "read_positions" in line
    assert "工具：portfolio" in line
    assert "completed" in line
    assert "analysis: completed" in line
    assert "依赖: market" in line
    assert "目标: 先确认真实仓位" in line
    assert "验收: 输出持仓风险" in line
    assert "边界: 不写入交易" in line


def test_workflow_detail_step_line_includes_effective_tool_scope():
    line = _workflow_detail_step_line(
        {
            "step_id": "review",
            "title": "复盘持仓",
            "agent": "task",
            "status": "running",
            "tool_scope": [],
            "effective_tool_scope": ["portfolio", "analyze_stock"],
        }
    )

    assert "可用工具：portfolio, analyze_stock" in line


def test_workflow_control_intent_requires_explicit_control_action():
    assert _workflow_control_intent("解释一下 workflow 是什么") is None
    assert _workflow_control_intent("查看 workflow wf_abc123") == ("show", "wf_abc123")
    assert _workflow_control_intent("workflow wf_abc123 详情") == ("show", "wf_abc123")
    assert _workflow_control_intent("把 workflow wf_abc123 的脚本打开") == ("script", "wf_abc123")
    assert _workflow_control_intent("看 workflow wf_abc123 的事件") == ("events", "wf_abc123")
    assert _workflow_control_intent("打开 workflow wf_abc123 日志") == ("events", "wf_abc123")
    assert _workflow_control_intent("workflow 运行状态") == ("status", "")
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


def test_system_notification_queue_item_is_not_user_chat_role():
    item = _system_notification_queue_item("后台任务完成")
    message = {"role": "user", "content": item["content"], "_system_notification": True}

    assert item == {"type": "system_notification", "content": "后台任务完成"}
    assert _is_system_notification_message(message)
    assert not _is_system_notification_message({"role": "user", "content": "后台任务完成"})
    assert _chatlog_role_for_turn(system_notification=True) == "system"
    assert _chatlog_role_for_turn(system_notification=False) == "user"
