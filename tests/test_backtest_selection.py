from __future__ import annotations

from core.wyckoff_engine import FunnelResult
from scripts.backtest_runner import _apply_regime_position_filter, _select_ai_input_codes


def test_all_formal_l4_selection_excludes_stage_only_candidates() -> None:
    result = FunnelResult(
        layer1_symbols=["000001", "000002"],
        layer2_symbols=["000001", "000002"],
        layer3_symbols=["000001", "000002"],
        top_sectors=[],
        triggers={"sos": [("000001", 2.0)]},
        stage_map={"000002": "Markup"},
        markup_symbols=["000002"],
        exit_signals={},
        channel_map={"000001": "点火破局", "000002": "主升通道"},
    )

    codes, score_map, track_map = _select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="NEUTRAL",
        selection_mode="all_formal_l4",
    )

    assert codes == ["000001"]
    assert score_map == {"000001": 2.0}
    assert track_map == {"000001": "Trend"}


def test_regime_position_filter_blocks_defensive_regimes() -> None:
    codes = ["A", "B", "C", "D"]

    assert _apply_regime_position_filter(codes, "PANIC_REPAIR") == []
    assert _apply_regime_position_filter(codes, "RISK_OFF") == []
    assert _apply_regime_position_filter(codes, "NEUTRAL") == ["A", "B"]
    assert _apply_regime_position_filter(codes, "RISK_ON") == ["A", "B"]
