from __future__ import annotations


def test_execution_decision_line_makes_observe_only_action_explicit() -> None:
    from workflows.funnel_render import _execution_decision_line

    line = _execution_decision_line("CRASH", 0)

    assert "不开新仓" in line
    assert "不从本报告选择买入标的" in line


def test_execution_decision_line_waits_for_ai_and_oms_confirmation() -> None:
    from workflows.funnel_render import _execution_decision_line

    line = _execution_decision_line("RISK_ON", 3)

    assert "3只进入AI复核" in line
    assert "OMS 风控同时确认" in line
