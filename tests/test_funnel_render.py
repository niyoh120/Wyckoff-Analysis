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


def test_render_context_treats_event_reversal_mainline_as_tradeable(monkeypatch) -> None:
    import workflows.funnel_render_context as render_context

    monkeypatch.setattr(render_context, "load_stock_name_map", lambda: {})
    monkeypatch.setattr(render_context, "fetch_sector_map", lambda: {})

    ctx = render_context.build_render_context(
        {},
        {
            "mainline_candidates": [
                {"code": "000006", "status": "事件主题修复候选"},
                {"code": "000007", "status": "主线观察"},
            ]
        },
    )

    assert ctx.mainline_tradeable_codes == ["000006"]
    assert [row["code"] for row in ctx.mainline_tradeable] == ["000006"]
