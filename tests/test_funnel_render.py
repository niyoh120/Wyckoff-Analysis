from __future__ import annotations


def test_execution_decision_line_makes_observe_only_action_explicit() -> None:
    from workflows.funnel_render import _execution_decision_line

    line = _execution_decision_line("CRASH", 0)

    assert "禁止新仓" in line
    assert "不从本报告选择买入标的" in line


def test_execution_decision_line_waits_for_ai_and_oms_confirmation() -> None:
    from workflows.funnel_render import _execution_decision_line

    line = _execution_decision_line("RISK_ON", 3)

    assert "可执行买入候选 3 只" in line
    assert "OMS 风控同时确认" in line


def test_policy_governance_line_surfaces_attribution_and_merged_weights() -> None:
    from workflows.funnel_render import _policy_governance_line

    line = _policy_governance_line(
        {
            "_attribution_signal_weights": {"lps": 0.5, "sos": 1.15},
            "_attribution_policy_meta": {
                "source": "远端",
                "report_date": "2026-07-04",
                "horizon": "5",
                "age_days": 0,
                "execution_policy": "shadow",
                "execution_scope": "tail_buy_and_funnel_shadow",
                "next_action": "manual_review_dynamic_on",
                "formal_dynamic_allowed": True,
                "tail_buy_weights_active": True,
                "funnel_shadow_weights_active": True,
                "funnel_formal_weights_active": False,
            },
            "_signal_weights": {"evr": 0.75, "lps": 0.5, "sos": 1.15},
        }
    )

    assert line.startswith("**策略治理调权**")
    assert (
        "归因 lps×0.50↓，sos×1.15↑"
        "（远端, report=2026-07-04, h=5, age=0d, mode=shadow, next=进入人工晋级评审（非正式生效）, active=尾盘+漏斗shadow）"
    ) in line
    assert "最终 evr×0.75↓，lps×0.50↓，sos×1.15↑" in line


def test_policy_governance_line_formats_scoped_weights() -> None:
    from workflows.funnel_render import _policy_governance_line

    line = _policy_governance_line(
        {
            "_signal_weights": {
                "lps|regime=RISK_ON|lane=trend_pullback|entry=wyckoff_structure": 0.5,
            },
        }
    )

    assert "lps[regime=RISK_ON, lane=trend_pullback, entry=wyckoff_structure]×0.50↓" in line


def test_policy_governance_line_sanitizes_invalid_weights() -> None:
    from workflows.funnel_render import _policy_governance_line

    line = _policy_governance_line({"_signal_weights": {"bad": "bad", "nan": float("nan"), "inf": float("inf")}})

    assert "bad×1.00" in line
    assert "nan×1.00" in line
    assert "inf×1.00" in line


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


def test_render_context_scores_capital_migration_theme_candidates(monkeypatch) -> None:
    import workflows.funnel_render_context as render_context

    monkeypatch.setattr(render_context, "load_stock_name_map", lambda: {})
    monkeypatch.setattr(render_context, "fetch_sector_map", lambda: {})
    monkeypatch.setattr(render_context, "FUNNEL_THEME_RADAR_BONUS_MAX", 0.0)
    monkeypatch.setattr(render_context, "FUNNEL_CAPITAL_MIGRATION_BONUS_MAX", 6.0)
    monkeypatch.setattr(render_context, "FUNNEL_CAPITAL_MIGRATION_PENALTY_MAX", 8.0)

    ctx = render_context.build_render_context(
        {"sos": [("000001", 10.0), ("000002", 10.0)]},
        {
            "theme_radar": {
                "strategic_candidates": [
                    {"code": "000001", "theme": "光模块", "theme_score": 0.8, "stock_score": 0.7},
                    {"code": "000002", "theme": "创新药医药", "theme_score": 0.7, "stock_score": 0.7},
                ]
            },
            "capital_migration": {
                "inflow": [{"theme": "CPO", "score": 0.75}],
                "outflow": [{"theme": "医药", "score": 0.50}],
            },
        },
    )

    assert ctx.capital_migration_bonus_map == {"000001": 4.5, "000002": -4.0}
    assert ctx.code_to_total_score["000001"] == 14.5
    assert ctx.code_to_total_score["000002"] == 6.0
    assert ctx.formal_sorted_codes == ["000001", "000002"]
    assert "资金迁入:光模块(+4.5)" in ctx.code_to_reasons["000001"]
    assert "资金撤出:创新药医药(-4.0)" in ctx.code_to_reasons["000002"]


def test_render_context_normalizes_candidate_entry_keys_and_keeps_best_entry(monkeypatch) -> None:
    import workflows.funnel_render_context as render_context

    monkeypatch.setattr(render_context, "load_stock_name_map", lambda: {})
    monkeypatch.setattr(render_context, "fetch_sector_map", lambda: {})

    ctx = render_context.build_render_context(
        {},
        {
            "candidate_entries": [
                {"code": "000001", "entry_type": "launchpad", "score": 80.0},
                {"code": "000001", "entry_type": "Early-Breakout", "score": 90.0},
            ]
        },
    )

    assert ctx.candidate_entry_map["000001"]["entry_type"] == "Early-Breakout"
    assert ctx.code_to_trigger_keys["000001"] == ["early_breakout"]
    assert ctx.code_to_total_score["000001"] == 90.0


def test_render_context_sanitizes_invalid_trigger_scores(monkeypatch) -> None:
    import workflows.funnel_render_context as render_context

    monkeypatch.setattr(render_context, "load_stock_name_map", lambda: {})
    monkeypatch.setattr(render_context, "fetch_sector_map", lambda: {})

    ctx = render_context.build_render_context(
        {"sos": [("BAD", "bad"), ("INF", float("inf")), ("NAN", float("nan")), ("GOOD", 4.25)]},
        {},
    )

    assert ctx.code_to_total_score == {"BAD": 0.0, "INF": 0.0, "NAN": 0.0, "GOOD": 4.25}
    assert ctx.formal_sorted_codes[0] == "GOOD"


def test_render_context_sanitizes_invalid_candidate_entry_scores(monkeypatch) -> None:
    import workflows.funnel_render_context as render_context

    monkeypatch.setattr(render_context, "load_stock_name_map", lambda: {})
    monkeypatch.setattr(render_context, "fetch_sector_map", lambda: {})

    ctx = render_context.build_render_context(
        {},
        {
            "candidate_entries": [
                {"code": "BAD", "entry_type": "launchpad", "score": "bad"},
                {"code": "INF", "entry_type": "launchpad", "score": float("inf")},
                {"code": "NAN", "entry_type": "launchpad", "score": float("nan")},
                {"code": "GOOD", "entry_type": "launchpad", "score": 8.0},
            ]
        },
    )

    assert ctx.code_to_total_score == {"BAD": 0.0, "INF": 0.0, "NAN": 0.0, "GOOD": 8.0}
