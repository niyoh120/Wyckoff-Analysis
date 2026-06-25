from __future__ import annotations

import pandas as pd

from core.backtest_metrics import calc_stratified_stats
from core.backtest_selection import select_ai_input_codes
from core.candidate_policy import CandidatePolicyConfig, apply_regime_position_filter, loss_guard_reason
from core.wyckoff_engine import FunnelResult


def _daily_position_df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": closes,
            "high": [x * 1.01 for x in closes],
            "low": [x * 0.99 for x in closes],
            "volume": [100.0 for _ in closes],
        }
    )


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
        leader_radar_symbols=[],
        leader_radar_rows=[],
    )

    codes, score_map, track_map = select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="NEUTRAL",
        selection_mode="all_formal_l4",
    )

    assert codes == ["000001"]
    assert score_map == {"000001": 2.0}
    assert track_map == {"000001": "Trend"}


def test_all_formal_l4_selection_respects_hard_cap() -> None:
    result = FunnelResult(
        layer1_symbols=["000001", "000002", "000003"],
        layer2_symbols=["000001", "000002", "000003"],
        layer3_symbols=["000001", "000002", "000003"],
        top_sectors=[],
        triggers={"sos": [("000001", 3.0), ("000002", 2.0), ("000003", 1.0)]},
        stage_map={},
        markup_symbols=[],
        exit_signals={},
        channel_map={"000001": "点火破局", "000002": "点火破局", "000003": "点火破局"},
        leader_radar_symbols=[],
        leader_radar_rows=[],
    )

    codes, score_map, track_map = select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="NEUTRAL",
        selection_mode="all_formal_l4",
        full_formal_l4_max=2,
    )

    assert codes == ["000001", "000002"]
    assert score_map == {"000001": 3.0, "000002": 2.0}
    assert track_map == {"000001": "Trend", "000002": "Trend"}


def test_tradeable_l4_selection_uses_formal_l4_without_l3_fallback() -> None:
    result = FunnelResult(
        layer1_symbols=[],
        layer2_symbols=[],
        layer3_symbols=["000001", "000003", "000004", "000005", "000006"],
        top_sectors=[],
        triggers={
            "sos": [("000001", 5.0), ("000003", 4.0)],
            "lps": [("000004", 2.0), ("000005", 1.0)],
            "spring": [("000005", 1.5)],
            "compression": [("000006", 1.0)],
        },
        stage_map={},
        markup_symbols=[],
        exit_signals={},
        channel_map={
            "000001": "主升通道",
            "000003": "点火破局",
            "000004": "吸筹通道",
            "000005": "吸筹通道",
            "000006": "吸筹通道",
        },
        leader_radar_symbols=[],
        leader_radar_rows=[],
    )

    codes, score_map, _ = select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="RISK_ON",
        selection_mode="tradeable_l4",
    )

    assert codes == ["000005", "000006"]
    assert score_map == {"000005": 1.5, "000006": 1.0}


def test_tradeable_l4_selection_prefers_candidate_board_when_available() -> None:
    result = FunnelResult(
        layer1_symbols=[],
        layer2_symbols=[],
        layer3_symbols=[],
        top_sectors=[],
        triggers={"sos": [("000001", 5.0)]},
        stage_map={},
        markup_symbols=[],
        exit_signals={},
        channel_map={},
        leader_radar_symbols=[],
        leader_radar_rows=[],
        candidate_entries=[
            {
                "code": "000002",
                "track": "future_leader",
                "entry_type": "launchpad",
                "score": 78.0,
            }
        ],
    )

    codes, score_map, track_map = select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="NEUTRAL",
        selection_mode="tradeable_l4",
    )

    assert codes == ["000002"]
    assert score_map == {"000002": 78.0}
    assert track_map == {"000002": "Trend"}


def test_tradeable_l4_candidate_board_allows_high_score_risk_on_early_breakout() -> None:
    result = FunnelResult(
        layer1_symbols=[],
        layer2_symbols=[],
        layer3_symbols=[],
        top_sectors=[],
        triggers={},
        stage_map={},
        markup_symbols=[],
        exit_signals={},
        channel_map={},
        leader_radar_symbols=[],
        leader_radar_rows=[],
        candidate_entries=[
            {"code": "000001", "track": "breakout", "entry_type": "early_breakout", "score": 92.0},
        ],
    )

    codes, score_map, track_map = select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="RISK_ON",
        selection_mode="tradeable_l4",
    )

    assert codes == ["000001"]
    assert score_map == {"000001": 92.0}
    assert track_map == {"000001": "Trend"}


def test_tradeable_l4_candidate_board_blocks_low_score_risk_on_early_breakout() -> None:
    result = FunnelResult(
        layer1_symbols=[],
        layer2_symbols=[],
        layer3_symbols=[],
        top_sectors=[],
        triggers={},
        stage_map={},
        markup_symbols=[],
        exit_signals={},
        channel_map={},
        leader_radar_symbols=[],
        leader_radar_rows=[],
        candidate_entries=[
            {"code": "000001", "track": "breakout", "entry_type": "early_breakout", "score": 69.0},
            {"code": "000002", "track": "future_leader", "entry_type": "launchpad", "score": 78.0},
        ],
    )

    codes, score_map, track_map = select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="RISK_ON",
        selection_mode="tradeable_l4",
    )

    assert codes == ["000002"]
    assert score_map == {"000002": 78.0}
    assert track_map == {"000002": "Trend"}


def test_tradeable_l4_candidate_board_prioritizes_launchpad_over_formal_score() -> None:
    result = FunnelResult(
        layer1_symbols=[],
        layer2_symbols=[],
        layer3_symbols=[],
        top_sectors=[],
        triggers={},
        stage_map={},
        markup_symbols=[],
        exit_signals={},
        channel_map={},
        leader_radar_symbols=[],
        leader_radar_rows=[],
        candidate_entries=[
            {"code": "000001", "track": "accumulation", "entry_type": "spring", "score": 100.0},
            {"code": "000002", "track": "future_leader", "entry_type": "launchpad", "score": 80.0},
        ],
    )

    codes, _, track_map = select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="NEUTRAL",
        selection_mode="tradeable_l4",
    )

    assert codes == ["000002", "000001"]
    assert track_map == {"000002": "Trend", "000001": "Accum"}


def test_tradeable_l4_candidate_board_selects_trend_lane_entry() -> None:
    result = FunnelResult(
        layer1_symbols=[],
        layer2_symbols=[],
        layer3_symbols=[],
        top_sectors=[],
        triggers={},
        stage_map={},
        markup_symbols=[],
        exit_signals={},
        channel_map={},
        leader_radar_symbols=[],
        leader_radar_rows=[],
        candidate_entries=[
            {"code": "000001", "track": "trend", "entry_type": "trend_lane_pullback", "score": 82.0},
        ],
    )

    codes, score_map, track_map = select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="NEUTRAL",
        selection_mode="tradeable_l4",
    )

    assert codes == ["000001"]
    assert score_map == {"000001": 82.0}
    assert track_map == {"000001": "Trend"}


def test_regime_position_filter_blocks_defensive_regimes() -> None:
    codes = ["A", "B", "C", "D"]

    assert apply_regime_position_filter(codes, "PANIC_REPAIR") == []
    assert apply_regime_position_filter(codes, "RISK_OFF") == []
    assert apply_regime_position_filter(codes, "NEUTRAL") == ["A", "B"]
    assert apply_regime_position_filter(codes, "RISK_ON") == ["A"]
    assert apply_regime_position_filter(codes, "BEAR_REBOUND") == []


def test_candidate_policy_config_overrides_regime_position_ratio() -> None:
    codes = ["A", "B", "C", "D"]
    config = CandidatePolicyConfig(position_ratio_by_regime={"NEUTRAL": 1.0})

    assert apply_regime_position_filter(codes, "NEUTRAL", config=config) == codes


def test_candidate_policy_config_can_disable_loss_guard() -> None:
    reason = loss_guard_reason(
        "000001",
        "RISK_ON",
        ["lps"],
        0.1,
        "",
        {},
        config=CandidatePolicyConfig(loss_guard_enabled=False),
    )

    assert reason == ""


def test_loss_guard_blocks_defensive_high_position_chase() -> None:
    df = _daily_position_df([10.0 + idx * 0.2 for idx in range(21)])

    reason = loss_guard_reason(
        "000001",
        "RISK_OFF",
        ["sos"],
        8.0,
        "点火破局",
        {"000001": df},
    )

    assert reason == "RISK_OFF20日高位追涨"


def test_loss_guard_keeps_defensive_spring_even_near_range_high() -> None:
    df = _daily_position_df([10.0 + idx * 0.2 for idx in range(21)])

    reason = loss_guard_reason(
        "000001",
        "RISK_OFF",
        ["spring"],
        8.0,
        "吸筹通道",
        {"000001": df},
    )

    assert reason == ""


def test_stratified_stats_include_exit_and_excursion_diagnostics() -> None:
    trades = pd.DataFrame(
        [
            {
                "track": "Trend",
                "regime": "RISK_ON",
                "trigger": "sos",
                "entry_price_source": "daily_close_fallback",
                "exit_reason": "stop_loss",
                "ret_pct": -6.9,
                "mfe_pct": 3.0,
                "mae_pct": -7.0,
            },
            {
                "track": "Trend",
                "regime": "RISK_ON",
                "trigger": "sos",
                "entry_price_source": "tail_1455",
                "exit_reason": "time_exit",
                "ret_pct": 4.0,
                "mfe_pct": 9.0,
                "mae_pct": -2.0,
            },
        ]
    )

    stats = calc_stratified_stats(trades, hold_days=5)

    assert stats["by_trigger"]["sos"]["stop_exit_rate_pct"] == 50.0
    assert stats["by_trigger"]["sos"]["avg_mfe_pct"] == 6.0
    assert stats["by_trigger"]["sos"]["avg_mae_pct"] == -4.5
    assert stats["by_exit_reason"]["stop_loss"]["trades"] == 1
    assert stats["by_entry_price_source"]["daily_close_fallback"]["trades"] == 1
