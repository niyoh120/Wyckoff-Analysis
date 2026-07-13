from cli.workflows.disagreement import build_workflow_disagreement_summary
from cli.workflows.executor import _has_material_disagreement


def _item(agent: str, text: str, status: str = "completed") -> dict:
    return {
        "step": {"agent": agent, "title": f"{agent} 视角"},
        "result": {"agent": agent, "status": status, "result": text},
    }


def test_disagreement_summary_detects_directional_conflict_without_raw_reasoning():
    summary = build_workflow_disagreement_summary(
        [
            _item("research", "趋势偏多，可关注买入机会。"),
            _item("trading", "风险偏高，建议减仓防御。"),
        ]
    )

    assert summary["conflict_type"] == "mixed_directional_signals"
    assert summary["decision_path_hint"] == "explain_cross_agent_conflict_before_any_action"
    assert summary["bullish_agents"] == [{"agent": "research", "step": "research 视角", "signal": "bullish"}]
    assert summary["bearish_agents"] == [{"agent": "trading", "step": "trading 视角", "signal": "bearish"}]
    assert "趋势偏多" not in str(summary)
    assert _has_material_disagreement(summary)


def test_disagreement_summary_marks_failed_agent_as_degraded_input():
    summary = build_workflow_disagreement_summary(
        [
            _item("analysis", "建议观望。"),
            _item("research", "", status="timeout"),
        ]
    )

    assert summary["conflict_type"] == "degraded_inputs"
    assert summary["degraded_steps"] == [{"agent": "research", "step": "research 视角", "status": "timeout"}]
    assert _has_material_disagreement(summary)


def test_disagreement_summary_stays_hidden_when_agents_are_aligned():
    summary = build_workflow_disagreement_summary(
        [
            _item("research", "趋势偏多。"),
            _item("analysis", "结构偏多。"),
        ]
    )

    assert summary["conflict_type"] == "aligned_bullish"
    assert not _has_material_disagreement(summary)
