from __future__ import annotations

from types import SimpleNamespace

from core.recommendation_payload import build_recommendation_payload
from workflows.funnel_ai_selection import FunnelAiSelection
from workflows.funnel_report_payload import display_score, funnel_run_details, selection_source, stage_name


def _ctx(**overrides):
    base = {
        "accum_stage_map": {"000001": "Accum_C"},
        "all_df_map": {"000001": "df"},
        "bypass_triggers": {},
        "candidate_entries": [],
        "candidate_entry_map": {},
        "code_to_total_score": {"000001": 3.5},
        "external_seed_triggers": {},
        "formal_hit_set": {"000001"},
        "formal_triggers": {},
        "leader_radar_rows": [],
        "leader_radar_symbols": set(),
        "l2_bypass_set": set(),
        "markup_symbols": set(),
        "metrics": {"layer3_score_map": {}},
        "name_map": {"000001": "平安银行"},
        "review_triggers": {},
        "sector_map": {"000001": "银行"},
        "strategic_l2_bypass_set": set(),
        "strategic_l2_bypass_triggers": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _selection() -> FunnelAiSelection:
    return FunnelAiSelection(
        selected_for_ai=["000001"],
        trend_selected=["000001"],
        accum_selected=[],
        score_map={"000001": 2.0},
        ai_policy={"shadow_added": ["000001"]},
        theme_promoted_count=0,
    )


def test_funnel_payload_helpers_preserve_stage_source_and_score_priority():
    ctx = _ctx(candidate_entry_map={"000001": {"state": "Breakout"}})

    assert stage_name(ctx, "000001") == "Breakout"
    assert selection_source(ctx, "000001") == "alpha_candidate"
    assert display_score(ctx, _selection(), "000001") == 3.5


def test_funnel_run_details_keeps_report_payload_fields():
    details = funnel_run_details(_ctx(), _selection(), content="内容", title="标题", symbols=[{"code": "000001"}])

    assert details["content"] == "内容"
    assert details["title"] == "标题"
    assert details["symbols_for_report"] == [{"code": "000001"}]
    assert details["selected_for_ai"] == ["000001"]
    assert details["shadow_added"] == ["000001"]
    assert details["name_map"] == {"000001": "平安银行"}


def test_recommendation_payload_keeps_capital_migration_bonus():
    payload = build_recommendation_payload(
        20260630,
        [
            {
                "code": "000001",
                "name": "平安银行",
                "tag": "SOS、资金迁入",
                "priority_score": 14.5,
                "capital_migration_bonus": 4.5,
            }
        ],
        {},
        {},
    )

    assert payload[0]["capital_migration_bonus"] == 4.5
