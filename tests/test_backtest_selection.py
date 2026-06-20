from __future__ import annotations

import pandas as pd

from core.wyckoff_engine import FunnelResult
from scripts.backtest_runner import _apply_regime_position_filter, _calc_stratified_stats, _select_ai_input_codes


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


def test_all_formal_l4_selection_respects_hard_cap(monkeypatch) -> None:
    from scripts import backtest_runner

    monkeypatch.setattr(backtest_runner, "BACKTEST_FULL_FORMAL_L4_MAX", 2)
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

    codes, score_map, track_map = backtest_runner._select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="NEUTRAL",
        selection_mode="all_formal_l4",
    )

    assert codes == ["000001", "000002"]
    assert score_map == {"000001": 3.0, "000002": 2.0}
    assert track_map == {"000001": "Trend", "000002": "Trend"}


def test_tradeable_l4_selection_uses_quota_and_loss_guard() -> None:
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

    codes, score_map, _ = _select_ai_input_codes(
        result=result,
        day_df_map={},
        sector_map={},
        regime="RISK_ON",
        selection_mode="tradeable_l4",
    )

    assert "000001" not in codes
    assert "000003" in codes
    assert "000004" not in codes
    assert "000005" in codes
    assert "000006" in codes
    assert score_map["000003"] > 0


def test_regime_position_filter_blocks_defensive_regimes() -> None:
    codes = ["A", "B", "C", "D"]

    assert _apply_regime_position_filter(codes, "PANIC_REPAIR") == []
    assert _apply_regime_position_filter(codes, "RISK_OFF") == []
    assert _apply_regime_position_filter(codes, "NEUTRAL") == ["A", "B"]
    assert _apply_regime_position_filter(codes, "RISK_ON") == ["A"]
    assert _apply_regime_position_filter(codes, "BEAR_REBOUND") == ["A"]


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

    stats = _calc_stratified_stats(trades, hold_days=5)

    assert stats["by_trigger"]["sos"]["stop_exit_rate_pct"] == 50.0
    assert stats["by_trigger"]["sos"]["avg_mfe_pct"] == 6.0
    assert stats["by_trigger"]["sos"]["avg_mae_pct"] == -4.5
    assert stats["by_exit_reason"]["stop_loss"]["trades"] == 1
    assert stats["by_entry_price_source"]["daily_close_fallback"]["trades"] == 1
