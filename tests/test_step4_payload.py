from __future__ import annotations

from workflows.step4_models import PositionItem
from workflows.step4_payload import build_candidate_meta_map, candidate_context_line, prepend_candidate_context


def test_build_candidate_meta_map_keeps_capital_migration_bonus_and_source() -> None:
    meta_map = build_candidate_meta_map(
        [
            {
                "code": "000390",
                "name": "晨光",
                "priority_score": 91,
                "funnel_score": 88,
                "capital_migration_bonus": 4.5,
                "source_type": "supabase_recommendation_tracking",
            }
        ],
        positions=[],
    )

    meta = meta_map["000390"]
    assert meta.funnel_score == 91
    assert meta.capital_migration_bonus == 4.5
    assert meta.source_type == "supabase_recommendation_tracking"


def test_candidate_context_line_exposes_score_source_and_capital_migration() -> None:
    line = candidate_context_line(
        {
            "code": "000390",
            "priority_score": 91,
            "capital_migration_bonus": 4.5,
            "selection_source": "二次确认",
            "candidate_lane": "mainline",
        }
    )

    assert "score=91.00" in line
    assert "资金迁移加分=+4.50" in line
    assert "来源=二次确认" in line
    assert "通道=mainline" in line


def test_prepend_candidate_context_keeps_payload_header_first() -> None:
    payload = "• 000390 晨光\n  [价格锚点] 最新收盘价:10.00\n"

    got = prepend_candidate_context(payload, {"priority_score": 91, "capital_migration_bonus": -3.25})

    assert got.startswith("• 000390 晨光\n  [候选归因]")
    assert "资金迁移扣分=-3.25" in got


def test_build_candidate_meta_map_preserves_existing_holding_source() -> None:
    meta_map = build_candidate_meta_map(
        [{"code": "000001", "name": "平安银行", "capital_migration_bonus": 4.5}],
        positions=[PositionItem(code="000001", name="平安银行", cost=10, buy_dt="2026-05-10", shares=1000)],
    )

    assert meta_map["000001"].source_type == "holding"
