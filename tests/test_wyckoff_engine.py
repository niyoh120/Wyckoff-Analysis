"""core/wyckoff_engine.py 冒烟测试。"""

from __future__ import annotations

import pandas as pd

from core.wyckoff_engine import (
    FunnelConfig,
    FunnelResult,
    _compute_stop_loss,
    _detect_compression,
    _effective_entry_max_bias_200,
    _is_holiday_grace,
    _latest_trade_date,
    _sorted_if_needed,
    allocate_ai_candidates,
    detect_leader_radar,
    layer1_filter,
    layer2_strength_detailed,
    layer3_sector_resonance,
    resolve_ai_candidate_policy,
)


def _make_df(dates, closes, volumes=None, amounts=None) -> pd.DataFrame:
    n = len(dates)
    opens = closes
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    vols = volumes or [1_000_000] * n
    amount = amounts if amounts is not None else [100_000_000] * n
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": opens,
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": vols,
            "amount": amount,
        }
    )


class TestSortedIfNeeded:
    def test_already_sorted(self):
        df = _make_df(["2024-01-01", "2024-01-02", "2024-01-03"], [10, 11, 12])
        result = _sorted_if_needed(df)
        assert list(result["close"]) == [10, 11, 12]

    def test_reverse_sorted(self):
        df = _make_df(["2024-01-03", "2024-01-02", "2024-01-01"], [12, 11, 10])
        result = _sorted_if_needed(df)
        assert list(result["close"]) == [10, 11, 12]


class TestLatestTradeDate:
    def test_returns_last_date(self):
        df = _make_df(["2024-01-01", "2024-01-02", "2024-01-03"], [10, 11, 12])
        result = _latest_trade_date(df)
        assert pd.Timestamp(result) == pd.Timestamp("2024-01-03")

    def test_empty_df_returns_none(self):
        df = pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])
        result = _latest_trade_date(df)
        assert result is None


class TestLayer1Filter:
    def test_filters_st_stocks(self):
        """L1 应剔除 ST 股票（名称含 ST）。"""
        cfg = FunnelConfig()
        # 准备一只正常股和一只 ST 股
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        closes = [10 + i * 0.01 for i in range(100)]
        df = _make_df(dates.strftime("%Y-%m-%d").tolist(), closes)

        name_map = {"000001": "平安银行", "000002": "ST 万科"}
        # 给足够大的市值和成交额，让非 ST 股通过
        mcap = {"000001": 5e10, "000002": 5e10}
        df_map = {"000001": df.copy(), "000002": df.copy()}

        result = layer1_filter(["000001", "000002"], name_map, mcap, df_map, cfg)
        assert "000002" not in result  # ST 被剔除

    def test_accepts_star_board_but_rejects_bse(self):
        cfg = FunnelConfig()
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        closes = [10 + i * 0.01 for i in range(100)]
        df = _make_df(dates.strftime("%Y-%m-%d").tolist(), closes)

        name_map = {"688001": "华兴源创", "689009": "科创样本", "830001": "北交样本"}
        mcap = {code: 100.0 for code in name_map}
        df_map = {code: df.copy() for code in name_map}

        result = layer1_filter(list(name_map), name_map, mcap, df_map, cfg)

        assert "688001" in result
        assert "689009" in result
        assert "830001" not in result

    def test_rejects_single_day_amount_spike_distortion(self):
        cfg = FunnelConfig()
        dates = pd.date_range("2024-01-01", periods=20, freq="B")
        closes = [10.0] * 20
        stable = _make_df(dates.strftime("%Y-%m-%d").tolist(), closes, amounts=[60_000_000] * 20)
        distorted = _make_df(
            dates.strftime("%Y-%m-%d").tolist(),
            closes,
            amounts=[1_000_000] * 19 + [1_000_000_000],
        )

        result = layer1_filter(
            ["000001", "000002"],
            {"000001": "稳定成交", "000002": "单日巨量"},
            {},
            {"000001": stable, "000002": distorted},
            cfg,
        )

        assert result == ["000001"]


class TestIsHolidayGrace:
    def test_normal_day_no_grace(self):
        df = _make_df(["2024-01-02", "2024-01-03"], [10, 11])
        assert _is_holiday_grace(df, 1) is False

    def test_weekend_no_grace(self):
        df = _make_df(["2024-01-05", "2024-01-08"], [10, 11])
        assert _is_holiday_grace(df, 1) is True

    def test_holiday_gap_triggers_grace(self):
        df = _make_df(["2024-09-27", "2024-10-08"], [10, 11])
        assert _is_holiday_grace(df, 1) is True

    def test_grace_disabled(self):
        df = _make_df(["2024-09-27", "2024-10-08"], [10, 11])
        assert _is_holiday_grace(df, 0) is False

    def test_grace_day2_still_active(self):
        df = _make_df(["2024-09-27", "2024-10-08", "2024-10-09"], [10, 11, 12])
        assert _is_holiday_grace(df, 1) is False
        assert _is_holiday_grace(df, 2) is True

    def test_grace_day3_expired(self):
        df = _make_df(
            ["2024-09-27", "2024-10-08", "2024-10-09", "2024-10-10"],
            [10, 11, 12, 13],
        )
        assert _is_holiday_grace(df, 2) is False
        assert _is_holiday_grace(df, 3) is True


class TestComputeStopLoss:
    def test_markup_trailing_stop(self):
        cfg = FunnelConfig()
        n = 250
        closes = pd.Series([10.0 + i * 0.05 for i in range(n)])
        lows = closes * 0.99
        highs = closes * 1.01
        price, reason = _compute_stop_loss(closes, lows, highs, "Markup", cfg)
        assert price is not None
        assert "主升趋势破位" in reason

    def test_accum_bottom_stop(self):
        cfg = FunnelConfig()
        n = 250
        closes = pd.Series([10.0] * n)
        lows = pd.Series([9.5] * n)
        highs = pd.Series([10.5] * n)
        price, reason = _compute_stop_loss(closes, lows, highs, "Accum_B", cfg)
        assert price is not None
        assert "吸筹底线" in reason


class TestLeaderRadar:
    def test_detects_independent_markup_watchlist(self):
        cfg = FunnelConfig()
        dates = pd.date_range("2024-01-01", periods=140, freq="B")
        strong_closes = [5.0 + i * 0.08 for i in range(140)]
        flat_closes = [10.0] * 140
        strong = _make_df(
            dates.strftime("%Y-%m-%d").tolist(), strong_closes, volumes=[1_000_000] * 135 + [1_200_000] * 5
        )
        flat = _make_df(dates.strftime("%Y-%m-%d").tolist(), flat_closes)

        rows = detect_leader_radar(
            ["000001", "000002"],
            {"000001": strong, "000002": flat},
            {"000001": "机器人"},
            {"000001": "主升通道"},
            cfg,
        )

        assert [row["code"] for row in rows] == ["000001"]
        assert rows[0]["risk"] == "主升跟踪"
        assert "60日" in rows[0]["reason"]


class TestDetectCompression:
    def _build_compression_df(self):
        n = 60
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        closes = [10.0] * n
        highs = [10.0 + (0.5 if i < 40 else 0.5 * (0.7 ** (i - 40))) for i in range(n)]
        lows = [10.0 - (0.5 if i < 40 else 0.5 * (0.7 ** (i - 40))) for i in range(n)]
        vols = [1_000_000 if i < 40 else int(600_000 * (0.9 ** (i - 40))) for i in range(n)]
        return pd.DataFrame(
            {
                "date": dates,
                "open": closes,
                "close": closes,
                "high": highs,
                "low": lows,
                "volume": vols,
                "pct_chg": [0.0] * n,
            }
        )

    def test_detects_compression(self):
        cfg = FunnelConfig()
        df = self._build_compression_df()
        result = _detect_compression(df, cfg)
        assert result is not None
        assert result < 1.0

    def test_rejects_high_position(self):
        cfg = FunnelConfig()
        n = 250
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        closes = [10.0 + i * 0.2 for i in range(n)]
        df = pd.DataFrame(
            {
                "date": dates,
                "open": closes,
                "close": closes,
                "high": [c * 1.001 for c in closes],
                "low": [c * 0.999 for c in closes],
                "volume": [1_000_000] * n,
                "pct_chg": [0.0] * n,
            }
        )
        result = _detect_compression(df, cfg)
        assert result is None

    def test_rejects_downtrend_compression(self):
        cfg = FunnelConfig()
        n = 60
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        closes = [12.0 - i * 0.03 for i in range(n)]
        highs = [c + (0.45 if i < 40 else 0.45 * (0.7 ** (i - 40))) for i, c in enumerate(closes)]
        lows = [c - (0.45 if i < 40 else 0.45 * (0.7 ** (i - 40))) for i, c in enumerate(closes)]
        vols = [1_000_000 if i < 40 else int(600_000 * (0.9 ** (i - 40))) for i in range(n)]
        df = pd.DataFrame(
            {
                "date": dates,
                "open": closes,
                "close": closes,
                "high": highs,
                "low": lows,
                "volume": vols,
                "pct_chg": [0.0] * n,
            }
        )

        assert _detect_compression(df, cfg) is None

    def test_effective_bias_limit_uses_star_and_trend_overrides(self):
        cfg = FunnelConfig()

        assert _effective_entry_max_bias_200("000001", "", cfg) == 25.0
        assert _effective_entry_max_bias_200("688001", "", cfg) == 40.0
        assert _effective_entry_max_bias_200("000001", "趋势延续", cfg) == 35.0

    def test_sos_bypass_requires_minimum_slow_rps(self):
        cfg = FunnelConfig()
        cfg.enable_ambush_channel = False
        cfg.enable_accumulation_channel = False
        cfg.enable_dry_vol_channel = False
        cfg.enable_rs_divergence_channel = False
        cfg.enable_trend_cont_channel = False
        cfg.enable_breakout_accel_channel = False
        cfg.enable_pre_ignition_watch = False
        cfg.sos_bypass_rps_slow_min = 75.0
        dates = pd.date_range("2024-01-01", periods=220, freq="B")
        weak_close = [10.0] * 219 + [10.7]
        strong_close = [10.0 + i * 0.08 for i in range(220)]

        weak = pd.DataFrame(
            {
                "date": dates,
                "open": [10.0] * 220,
                "close": weak_close,
                "high": [10.1] * 219 + [10.8],
                "low": [9.9] * 219 + [10.0],
                "volume": [1_000_000] * 219 + [4_000_000],
                "pct_chg": [0.0] * 219 + [7.0],
            }
        )
        strong = pd.DataFrame(
            {
                "date": dates,
                "open": strong_close,
                "close": strong_close,
                "high": [c * 1.01 for c in strong_close],
                "low": [c * 0.99 for c in strong_close],
                "volume": [1_000_000] * 220,
                "pct_chg": [0.5] * 220,
            }
        )

        passed, channel_map, _ = layer2_strength_detailed(
            ["LOW"],
            {"LOW": weak, "HIGH": strong},
            None,
            cfg,
            rps_universe=["LOW", "HIGH"],
        )

        assert passed == []
        assert channel_map == {}


class TestAllocateAiCandidates:
    def test_bear_rebound_uses_defensive_quota_family(self, monkeypatch):
        monkeypatch.setenv("FUNNEL_AI_TOTAL_CAP", "8")
        monkeypatch.setenv("FUNNEL_AI_BEAR_REBOUND_TREND", "1")
        monkeypatch.setenv("FUNNEL_AI_BEAR_REBOUND_ACCUM", "2")

        policy = resolve_ai_candidate_policy("BEAR_REBOUND")

        assert policy["quota_family"] == "BEAR_REBOUND"
        assert policy["trend_quota"] == 1
        assert policy["accum_quota"] == 2

    def test_evr_and_compression_only_hits_enter_quota_tracks(self):
        result = FunnelResult(
            layer1_symbols=["000001", "000002"],
            layer2_symbols=["000001", "000002"],
            layer3_symbols=["000001", "000002"],
            top_sectors=[],
            triggers={"evr": [("000001", 2.0)], "compression": [("000002", 0.4)]},
            stage_map={},
            markup_symbols=[],
            exit_signals={},
            channel_map={},
            leader_radar_symbols=[],
            leader_radar_rows=[],
        )

        trend, accum, scores = allocate_ai_candidates(
            result,
            [],
            "NEUTRAL",
            policy_override={
                "total_cap": 2,
                "trend_quota": 1,
                "accum_quota": 1,
                "max_trend_l3_fill": 0,
                "max_accum_l3_fill": 0,
            },
        )

        assert trend == ["000001"]
        assert accum == ["000002"]
        assert scores["000001"] > 0
        assert scores["000002"] > 0

    def test_sos_outranks_evr_after_downweight_iteration(self):
        result = FunnelResult(
            layer1_symbols=["000001", "000002"],
            layer2_symbols=["000001", "000002"],
            layer3_symbols=["000001", "000002"],
            top_sectors=[],
            triggers={"sos": [("000001", 4.0)], "evr": [("000002", 4.0)]},
            stage_map={},
            markup_symbols=[],
            exit_signals={},
            channel_map={"000001": "点火破局", "000002": "趋势延续"},
            leader_radar_symbols=[],
            leader_radar_rows=[],
        )

        _trend, _accum, scores = allocate_ai_candidates(
            result,
            [],
            "NEUTRAL",
            policy_override={
                "total_cap": 2,
                "trend_quota": 2,
                "accum_quota": 0,
                "max_trend_l3_fill": 0,
                "max_accum_l3_fill": 0,
            },
        )

        assert scores["000001"] > scores["000002"]


class TestSectorHeatBypass:
    def test_heat_bypass_includes_sector(self):
        cfg = FunnelConfig()
        cfg.sector_heat_bypass_min_count = 2
        n = 30
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        base_closes = [10.0 + i * 0.1 for i in range(n)]
        df_map = {}
        for code in ["A1", "A2", "B1"]:
            df_map[code] = pd.DataFrame(
                {
                    "date": dates,
                    "open": base_closes,
                    "close": base_closes,
                    "high": [c * 1.02 for c in base_closes],
                    "low": [c * 0.98 for c in base_closes],
                    "volume": [1_000_000] * n,
                }
            )
        sector_map = {"A1": "电气设备", "A2": "电气设备", "B1": "食品饮料"}
        result, top = layer3_sector_resonance(
            ["A1", "A2", "B1"],
            sector_map,
            cfg,
            base_symbols=["A1", "A2", "B1"],
            df_map=df_map,
        )
        assert "A1" in result
        assert "A2" in result
