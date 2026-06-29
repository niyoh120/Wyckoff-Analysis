from __future__ import annotations

import json

from cli.scratchpad import AgentScratchpad
from cli.tool_results import INLINE_TOOL_RESULT_MAX_CHARS, format_tool_result_for_context, serialize_tool_result


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
        "summary": {"total_scanned": 2000},
        "trade_mode": {"regime": "RISK_OFF", "action": "不新增买入"},
        "decision_brief": {
            "market_gate": "风险规避 / 不新增买入",
            "report_focus": [{"summary": "300750 宁德时代: LPS+SOS；只观察"}],
        },
        "action_plan": {"candidate_action": "只观察，不新增买入", "new_buy_allowed": False},
        "trigger_groups": {"huge": [{"code": f"{idx:06d}", "blob": "x" * 200} for idx in range(100)]},
        "top_candidates": [
            {"code": "300750", "name": "宁德时代", "score": 96.5, "triggers": ["lps", "sos"]},
        ],
        "symbols_for_report": ["300750"],
    }

    content = format_tool_result_for_context("screen_stocks", "call_screen", result, max_chars=1000)

    assert "result_ref:" in content
    assert '"top_candidates": [{"code": "300750"' in content
    assert "宁德时代" in content
    assert '"decision_brief": {"market_gate": "风险规避 / 不新增买入"' in content
    assert "300750 宁德时代: LPS+SOS；只观察" in content
    assert '"trade_mode": {"regime": "RISK_OFF", "action": "不新增买入"}' in content
    assert '"action_plan": {"candidate_action": "只观察，不新增买入", "new_buy_allowed": false}' in content
    assert "完整 trigger_groups 已写入 result_ref" in content
    assert '"trigger_groups"' not in content
    stored = list((tmp_path / "tool-results").glob("*.json"))
    assert len(stored) == 1
    assert json.loads(stored[0].read_text(encoding="utf-8"))["trigger_groups"]["huge"][0]["blob"] == "x" * 200
