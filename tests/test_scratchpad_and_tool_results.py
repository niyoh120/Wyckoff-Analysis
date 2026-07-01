from __future__ import annotations

import json

from cli.scratchpad import AgentScratchpad
from cli.tool_results import INLINE_TOOL_RESULT_MAX_CHARS, format_tool_result_for_context, serialize_tool_result
from utils.tool_result_preview import tool_result_brief_lines, tool_result_preview


class _Scalar:
    def __init__(self, value: float):
        self.value = value

    def item(self) -> float:
        return self.value


def test_scratchpad_records_jsonl_and_redacts_secrets(tmp_path):
    scratchpad = AgentScratchpad("看看 000001", session_id="session_x", scratchpad_dir=tmp_path)
    scratchpad.record_tool_result(
        "web_fetch",
        {"url": "https://example.com", "api_key": "secret-value"},
        {"ok": True, "token": "secret-token"},
        duration_ms=12,
    )
    scratchpad.record_compaction(
        before_messages=12,
        after_messages=5,
        metadata={"archive_ref": "archive://session_x/ctx_1", "messages_path": "/tmp/ctx.jsonl"},
    )
    scratchpad.record_final("完成", input_tokens=10, output_tokens=5, elapsed_s=0.5)

    lines = [json.loads(line) for line in scratchpad.path.read_text(encoding="utf-8").splitlines()]

    assert [line["type"] for line in lines] == ["init", "tool_result", "compaction", "final"]
    tool_entry = lines[1]
    assert tool_entry["args"]["api_key"] == "***REDACTED***"
    assert tool_entry["result"]["token"] == "***REDACTED***"
    assert tool_entry["durationMs"] == 12
    assert lines[2]["contextArchive"]["archive_ref"] == "archive://session_x/ctx_1"


def test_tool_result_serialization_replaces_nonfinite_numbers() -> None:
    content = serialize_tool_result(
        {
            "nan_score": float("nan"),
            "inf_score": float("inf"),
            "nested": [float("-inf"), _Scalar(float("nan")), 12.5],
        }
    )

    assert "NaN" not in content
    assert "Infinity" not in content
    assert json.loads(content) == {
        "nan_score": None,
        "inf_score": None,
        "nested": [None, None, 12.5],
    }


def test_large_tool_result_is_persisted_with_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    result = {"rows": ["x" * 1000 for _ in range(60)]}

    content = format_tool_result_for_context("screen_stocks", "call_1", result, max_chars=1000)

    assert "工具结果已卸载为可追溯节点" in content
    assert "node_id:" in content
    assert "result_ref:" in content
    assert "预览:" in content
    stored = list((tmp_path / "tool-results").glob("*.json"))
    assert len(stored) == 1
    assert json.loads(stored[0].read_text(encoding="utf-8"))["rows"][0] == "x" * 1000
    index_lines = (tmp_path / "tool-results" / "index.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(index_lines[0])["tool_call_id"] == "call_1"


def test_default_tool_result_budget_offloads_medium_json(tmp_path, monkeypatch):
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    result = {"rows": ["x" * 1000 for _ in range((INLINE_TOOL_RESULT_MAX_CHARS // 1000) + 2)]}

    content = format_tool_result_for_context("screen_stocks", "call_2", result)

    assert "result_ref:" in content
    assert len(list((tmp_path / "tool-results").glob("*.json"))) == 1


def test_screen_stocks_large_result_preview_prioritizes_top_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    result = {
        "ok": True,
        "board": "chinext",
        "scan_scope": {"scope": "bounded", "board": "chinext", "limit": 200, "total_scanned": 200},
        "summary": {"total_scanned": 2000},
        "data_quality": {
            "status": "partial",
            "coverage_pct": 94.5,
            "warnings": ["11只股票拉取失败", "数据覆盖率 94.5%"],
            "action": "候选可参考，但需要优先复核缺失数据影响",
        },
        "trade_mode": {"regime": "RISK_OFF", "action": "不新增买入"},
        "decision_brief": {
            "market_gate": "风险规避 / 不新增买入",
            "report_focus": [
                {
                    "summary": "300750 宁德时代: LPS+SOS；只观察",
                    "risk_factors": ["大盘风险闸门关闭"],
                    "action_status": "blocked_by_market_gate",
                }
            ],
        },
        "selection_brief": {
            "status": "ready_for_ai_review",
            "headline": "本轮首选可进入 AI 研报复核: 300750 宁德时代",
            "best_codes": ["300750"],
            "best_candidates": [
                {
                    "code": "300750",
                    "name": "宁德时代",
                    "quality_factors": ["高优先级研报候选"],
                    "risk_factors": ["大盘风险闸门关闭"],
                    "action_status": "blocked_by_market_gate",
                }
            ],
            "tool_handoff": {"tool": "generate_ai_report", "args": {"stock_codes": ["300750"]}},
        },
        "action_plan": {
            "candidate_action": "只观察，不新增买入",
            "new_buy_allowed": False,
            "review_targets": {
                "codes": ["300750"],
                "status": "ready",
                "tool": "generate_ai_report",
                "args": {"stock_codes": ["300750"]},
            },
            "long_debug_payload": "x" * 1200,
        },
        "trigger_groups": {"huge": [{"code": f"{idx:06d}", "blob": "x" * 200} for idx in range(100)]},
        "top_candidates": [
            {
                "code": "300750",
                "name": "宁德时代",
                "score": 96.5,
                "triggers": ["lps", "sos"],
                "quality_factors": ["高优先级研报候选"],
                "risk_factors": ["大盘风险闸门关闭"],
                "action_status": "blocked_by_market_gate",
            },
        ],
        "symbols_for_report": ["300750"],
    }

    content = format_tool_result_for_context("screen_stocks", "call_screen", result, max_chars=1000)

    assert "result_ref:" in content
    assert '"top_candidates": [{"code": "300750"' in content
    assert "宁德时代" in content
    assert '"decision_brief": {"market_gate": "风险规避 / 不新增买入"' in content
    assert '"selection_brief": {"status": "ready_for_ai_review"' in content
    assert '"candidate_conclusion": {"line": "候选结论: 首选 300750 宁德时代' in content
    assert "证据: 触发分96.5" in content
    assert '"scan_scope": {"scope": "bounded", "board": "chinext", "limit": 200, "total_scanned": 200}' in content
    assert '"data_quality": {"status": "partial"' in content
    assert "候选可参考，但需要优先复核缺失数据影响" in content
    assert "本轮首选可进入 AI 研报复核: 300750 宁德时代" in content
    assert "300750 宁德时代: LPS+SOS；只观察" in content
    assert '"risk_factors": ["大盘风险闸门关闭"]' in content
    assert '"action_status": "blocked_by_market_gate"' in content
    assert '"trade_mode": {"regime": "RISK_OFF", "action": "不新增买入"}' in content
    assert '"tool": "generate_ai_report"' in content
    assert '"args": {"stock_codes": ["300750"]}' in content
    assert "完整 trigger_groups 已保留在完整结果中" in content
    assert '"trigger_groups"' not in content
    assert "long_debug_payload" not in content
    stored = list((tmp_path / "tool-results").glob("*.json"))
    assert len(stored) == 1
    assert json.loads(stored[0].read_text(encoding="utf-8"))["trigger_groups"]["huge"][0]["blob"] == "x" * 200


def test_screen_stocks_brief_lines_surface_candidate_risk_status():
    result = {
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
                "next_step": "只观察，等待风险闸门重新打开",
            },
        },
        "top_candidates": [
            {
                "code": "000001",
                "name": "平安银行",
                "why": "触发:SOS；缩量回踩",
                "score": 8.5,
                "risk_factors": ["未进入本轮研报候选"],
                "action_status": "watch_only",
            }
        ],
    }

    lines = tool_result_brief_lines("screen_stocks", result)

    assert lines == [
        "本轮首选可进入 AI 研报复核: 300750 宁德时代",
        "候选结论: 首选 300750 宁德时代 · 风险闸门关闭 · 证据: 优先分12.5；动态分4.2 · 亮点: 高优先级研报候选；趋势线 · 风险: 大盘风险闸门关闭 · 下一步: 只观察，等待风险闸门重新打开",
        "000001 平安银行 · 观察池 · 证据: 触发分8.5 · 亮点: 触发:SOS；缩量回踩 · 风险: 未进入本轮研报候选",
    ]


def test_screen_stocks_preview_surfaces_data_quality_gate():
    result = {
        "selection_brief": {
            "headline": "本轮有候选，但数据质量未过关: 300750 宁德时代",
            "primary_pick": {
                "code": "300750",
                "name": "宁德时代",
                "priority_score": 12.5,
                "quality_factors": ["高优先级研报候选"],
                "risk_factors": ["不要直接据此选股，先重跑或缩小扫描范围"],
                "action_status": "blocked_by_data_quality",
                "next_step": "数据质量不足，先重跑或缩小扫描范围",
            },
        },
        "action_plan": {
            "new_buy_allowed": False,
            "ai_review_allowed": False,
            "data_quality_gate": {
                "status": "degraded",
                "reason": "不要直接据此选股，先重跑或缩小扫描范围",
            },
            "review_targets": {
                "codes": ["300750"],
                "status": "blocked_by_data_quality",
                "reason": "不要直接据此选股，先重跑或缩小扫描范围",
            },
        },
    }

    preview = tool_result_preview("screen_stocks", result)
    lines = tool_result_brief_lines("screen_stocks", result)

    assert '"ai_review_allowed": false' in preview
    assert '"data_quality_gate": {"status": "degraded"' in preview
    assert '"status": "blocked_by_data_quality"' in preview
    assert "候选结论: 首选 300750 宁德时代" in preview
    assert "护栏: 不要直接据此选股，先重跑或缩小扫描范围" in preview
    assert lines == [
        "本轮有候选，但数据质量未过关: 300750 宁德时代",
        "候选结论: 首选 300750 宁德时代 · 数据质量未过关 · 证据: 优先分12.5 · 亮点: 高优先级研报候选 · 风险: 不要直接据此选股，先重跑或缩小扫描范围 · 护栏: 不要直接据此选股，先重跑或缩小扫描范围 · 下一步: 数据质量不足，先重跑或缩小扫描范围",
    ]


def test_screen_stocks_preview_surfaces_quality_gate():
    reason = "000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00"
    result = {
        "selection_brief": {
            "headline": "本轮只有观察候选: 000013 低质量候选",
            "primary_pick": {
                "code": "000013",
                "name": "低质量候选",
                "risk_adjusted_quality_score": 65.0,
                "risk_factors": [reason],
                "action_status": "watch_only",
                "next_step": "观察池跟踪，暂不进入本轮AI复核",
            },
        },
        "action_plan": {
            "new_buy_allowed": False,
            "ai_review_allowed": False,
            "quality_gate": {
                "status": "blocked_by_quality_gate",
                "reason": reason,
                "blocked_count": 1,
            },
            "review_targets": {
                "codes": [],
                "status": "blocked_by_quality_gate",
                "reason": reason,
            },
        },
    }

    preview = tool_result_preview("screen_stocks", result)
    lines = tool_result_brief_lines("screen_stocks", result)

    assert '"quality_gate": {"status": "blocked_by_quality_gate"' in preview
    assert '"ai_review_allowed": false' in preview
    assert "候选结论: 首选 000013 低质量候选" in preview
    assert "护栏: 000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00" in preview
    assert lines == [
        "本轮只有观察候选: 000013 低质量候选",
        "候选结论: 首选 000013 低质量候选 · 观察池 · 证据: 风险调整分65 · 风险: 000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00 · 护栏: 000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00 · 下一步: 观察池跟踪，暂不进入本轮AI复核",
    ]


def test_screen_stocks_brief_lines_use_symbols_for_report_handoff():
    result = {
        "symbols_for_report": [
            {
                "code": "300750",
                "name": "宁德时代",
                "candidate_shadow_score": 92.0,
                "candidate_shadow_grade": "S",
                "action_status": "ready_for_ai_review",
                "next_step": "生成 AI 研报",
            }
        ]
    }

    lines = tool_result_brief_lines("screen_stocks", result)

    assert lines == [
        "候选结论: 首选 300750 宁德时代 · 可进入AI复核 · 证据: 候选影子S/92 · 下一步: 生成 AI 研报",
    ]


def test_recommendation_event_eval_large_result_preview_preserves_policy_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    result = {
        "ok": True,
        "job_kind": "recommendation_event_eval",
        "result_summary": (
            "推荐事件评估: ready=12/20, hit=60%, ranking_decision=candidate\n"
            "排序接入候选: candidate_shadow_then_score top1 已通过样本/lift/风险门槛\n"
            "最新候选(20260601, candidate_shadow_then_score): 300750 宁德时代"
        ),
        "summary": {
            "all": {"rows_ready": 12, "rows_total": 20, "hit_rate_pct": 60.0},
            "ranking_decision": {
                "status": "candidate",
                "recommended_strategy": "candidate_shadow_then_score",
                "recommended_top_k": 1,
                "reason": "candidate_shadow_then_score top1 passed lift and risk gates",
            },
        },
        "policy_selection": {
            "status": "candidate",
            "selection_strategy": "candidate_shadow_then_score",
            "top_k": 1,
            "recommend_date": 20260601,
            "uses_promoted_ranking": True,
            "action_plan": {
                "primary_action": "generate_ai_report",
                "candidate_action": "generate_ai_report",
                "new_buy_allowed": False,
                "ai_review_allowed": True,
                "trade_readiness": "research_only",
                "review_status": "ready_for_ai_review",
                "reason": "只读推荐事件评估已通过排序接入门槛，可进入 AI 研报；不直接触发买入",
                "next_step": "生成 AI 研报并结合持仓形成攻防决策",
                "next_tool": {"tool": "generate_ai_report", "args": {"stock_codes": ["300750"]}},
            },
            "picks": [
                {
                    "rank": 1,
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
                    "label_ready": False,
                    "label_status": "partial_window",
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
                    "risk_factors": ["最新候选的未来窗口标签尚未成熟"],
                }
            ],
        },
        "events": [{"code": f"{idx:06d}", "blob": "x" * 200} for idx in range(20)],
    }

    content = format_tool_result_for_context("web_background_job", "call_eval", result, max_chars=1000)
    preview = tool_result_preview("web_background_job", result)
    lines = tool_result_brief_lines("web_background_job", result)

    assert "result_ref:" in content
    assert "ranking_decision=candidate" in content
    assert "最新候选(20260601, candidate_shadow_then_score): 300750 宁德时代" in content
    assert '"candidate_shadow_grade": "S"' in preview
    assert '"trade_readiness": "research_only"' in preview
    assert '"new_buy_allowed": false' in preview
    assert '"action_status": "ready_for_ai_review"' in preview
    assert '"candidate_conclusion"' in preview
    assert "候选结论: 首选 300750 宁德时代" in preview
    assert '"risk_adjusted_quality_score": 87.0' in preview
    assert "证据: 漏斗分89.5；候选影子S/92；入场A/84；风险调整分87" in preview
    assert '"candidate_guard_summary"' in preview
    assert "候选标签未成熟，禁止直接买入" in preview
    assert "护栏: 候选标签未成熟" in preview
    assert "最新候选的未来窗口标签尚未成熟" in preview
    assert '"events"' not in content
    assert lines == [
        "推荐事件评估: ready=12/20, hit=60%, ranking_decision=candidate",
        "候选结论: 首选 300750 宁德时代 · 可进入AI复核 · 证据: 漏斗分89.5；候选影子S/92；入场A/84；风险调整分87 · 亮点: 候选影子评级 S · 风险: 最新候选的未来窗口标签尚未成熟 · 护栏: 候选标签未成熟，禁止直接买入 · 下一步: 生成 AI 研报并结合持仓形成攻防决策",
        "候选护栏: 1只禁止直接买入 · 300750 宁德时代(候选标签未成熟，禁止直接买入)",
    ]


def test_generate_ai_report_large_result_preview_preserves_handoff(tmp_path, monkeypatch):
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    report_text = "# 研报\n" + "量价结构良好。" * 500
    result = {
        "ok": True,
        "reason": "ok",
        "report_text": report_text,
        "model": "gpt-test",
        "stock_count": 2,
        "reviewed_codes": ["000001", "300750"],
        "reviewed_symbols": [
            {"code": "000001", "name": "平安银行", "tag": "chat_request"},
            {
                "code": "300750",
                "name": "宁德时代",
                "tag": "chat_request",
                "risk_factors": ["大盘风险闸门关闭"],
                "action_status": "blocked_by_market_gate",
            },
        ],
        "candidate_guard_summary": {
            "direct_buy_blocked_count": 1,
            "message": "以下候选仅可复核或观察，禁止直接买入",
            "candidates": [
                {
                    "code": "300750",
                    "name": "宁德时代",
                    "reason": "候选状态 blocked_by_market_gate 不允许直接买入",
                    "action_status": "blocked_by_market_gate",
                    "risk_factors": ["大盘风险闸门关闭"],
                }
            ],
        },
        "next_action": "研报已完成；候选存在禁止直接买入边界，下一步只进入组合攻防复核",
        "next_tool": {
            "tool": "generate_strategy_decision",
            "args": {},
            "reason": "研报已完成，可继续生成组合攻防复核；候选护栏禁止把观察/未成熟候选直接写成买入",
        },
    }

    content = format_tool_result_for_context("generate_ai_report", "call_report", result, max_chars=1000)
    lines = tool_result_brief_lines("generate_ai_report", result, max_lines=3)

    assert "result_ref:" in content
    assert '"reviewed_codes": ["000001", "300750"]' in content
    assert '"risk_factors": ["大盘风险闸门关闭"]' in content
    assert '"action_status": "blocked_by_market_gate"' in content
    assert '"candidate_guard_summary"' in content
    assert '"candidate_conclusion": {"line": "候选结论: 首选 300750 宁德时代' in content
    assert "护栏: 候选状态 blocked_by_market_gate 不允许直接买入" in content
    assert '"direct_buy_blocked_count": 1' in content
    assert '"tool": "generate_strategy_decision"' in content
    assert '"report_excerpt": "# 研报' in content
    assert report_text not in content
    assert lines == [
        "AI研报: reviewed=2, model=gpt-test, next=研报已完成；候选存在禁止直接买入边界，下一步只进入组合攻防复核",
        "候选结论: 首选 300750 宁德时代 · 风险闸门关闭 · 风险: 大盘风险闸门关闭 · 护栏: 候选状态 blocked_by_market_gate 不允许直接买入 · 下一步: 研报已完成；候选存在禁止直接买入边界，下一步只进入组合攻防复核",
        "候选护栏: 1只禁止直接买入 · 300750 宁德时代(候选状态 blocked_by_market_gate 不允许直接买入)",
    ]
    stored = list((tmp_path / "tool-results").glob("*.json"))
    assert len(stored) == 1
    assert json.loads(stored[0].read_text(encoding="utf-8"))["report_text"] == report_text


def test_generate_strategy_decision_large_result_preview_preserves_handoff(tmp_path, monkeypatch):
    monkeypatch.setenv("WYCKOFF_HOME", str(tmp_path))
    result = {
        "ok": True,
        "status": "skipped_notify_unconfigured",
        "reason": "skipped_notify_unconfigured",
        "report_source": "last_ai_report",
        "candidate_count": 1,
        "reviewed_codes": ["300750"],
        "reviewed_symbols": [
            {
                "code": "300750",
                "name": "宁德时代",
                "track": "Trend",
                "risk_factors": ["大盘风险闸门关闭"],
                "action_status": "blocked_by_market_gate",
            }
        ],
        "candidate_guard_summary": {
            "direct_buy_blocked_count": 1,
            "message": "以下候选仅可复核或观察，禁止直接买入",
            "candidates": [
                {
                    "code": "300750",
                    "name": "宁德时代",
                    "reason": "候选状态 blocked_by_market_gate 不允许直接买入",
                    "action_status": "blocked_by_market_gate",
                    "risk_factors": ["大盘风险闸门关闭"],
                }
            ],
        },
        "screen_summary": {"report_candidates": 1},
        "decision_brief": {
            "next_action": "允许候选进入AI复核",
            "report_focus": [{"code": "300750", "risk_factors": ["大盘风险闸门关闭"]}],
        },
        "next_action": "补充 Telegram 配置后可生成并发送 OMS 工单",
        "message": "已完成候选和研报交接，但未配置 Telegram。",
        "report_preview": "研报摘要" * 500,
    }

    content = format_tool_result_for_context("generate_strategy_decision", "call_strategy", result, max_chars=1000)
    lines = tool_result_brief_lines("generate_strategy_decision", result, max_lines=3)

    assert "result_ref:" in content
    assert '"report_source": "last_ai_report"' in content
    assert '"reviewed_codes": ["300750"]' in content
    assert '"risk_factors": ["大盘风险闸门关闭"]' in content
    assert '"action_status": "blocked_by_market_gate"' in content
    assert '"candidate_guard_summary"' in content
    assert '"candidate_conclusion": {"line": "候选结论: 首选 300750 宁德时代' in content
    assert "护栏: 候选状态 blocked_by_market_gate 不允许直接买入" in content
    assert '"direct_buy_blocked_count": 1' in content
    assert "候选状态 blocked_by_market_gate 不允许直接买入" in content
    assert "补充 Telegram 配置后可生成并发送 OMS 工单" in content
    assert result["report_preview"] not in content
    assert lines == [
        "攻防决策: status=skipped_notify_unconfigured, source=last_ai_report, reviewed=1, next=补充 Telegram 配置后可生成并发送 OMS 工单",
        "候选结论: 首选 300750 宁德时代 · 风险闸门关闭 · 风险: 大盘风险闸门关闭 · 护栏: 候选状态 blocked_by_market_gate 不允许直接买入 · 下一步: 补充 Telegram 配置后可生成并发送 OMS 工单",
        "候选护栏: 1只禁止直接买入 · 300750 宁德时代(候选状态 blocked_by_market_gate 不允许直接买入)",
    ]


def test_generate_strategy_decision_brief_labels_quality_gate_blocker():
    reason = "000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00"
    result = {
        "ok": False,
        "status": "blocked_by_quality_gate",
        "reason": reason,
        "report_source": "blocked_by_screen_quality_gate",
        "candidate_count": 0,
        "reviewed_codes": [],
        "next_action": "先保留观察候选，等待风险调整质量分达标后再生成策略决策",
    }

    lines = tool_result_brief_lines("generate_strategy_decision", result, max_lines=2)

    assert lines == [
        (
            "攻防决策: status=blocked_by_quality_gate, blocker=候选质量门槛未过, "
            "source=blocked_by_screen_quality_gate, reviewed=0, "
            "reason=000013 低质量候选 风险调整质量分 65.00 低于AI复核门槛 70.00, "
            "next=先保留观察候选，等待风险调整质量分达标后再生成策略决策"
        )
    ]
