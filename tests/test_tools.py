"""tools/ 层单元测试 — 测试 Phase 2 提取的纯逻辑 Tool 函数。"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from types import ModuleType, SimpleNamespace

import pandas as pd


def _money_flow_df(prev_close: float, latest_close: float, latest_amount: float) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=20, freq="D").strftime("%Y-%m-%d")
    close = [prev_close] * 19 + [latest_close]
    amount = [100_000_000.0] * 19 + [latest_amount]
    return pd.DataFrame({"date": dates, "close": close, "amount": amount})


def _benchmark_df(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(closes), freq="D").strftime("%Y-%m-%d")
    close = pd.Series(closes, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "close": close,
            "pct_chg": close.pct_change().fillna(0.0) * 100.0,
            "volume": [100_000_000.0] * len(closes),
        }
    )


def _benchmark_with_last_drop(drop_pct: float) -> pd.DataFrame:
    closes = [100.0 + i * 0.2 for i in range(220)]
    closes[-1] = closes[-2] * (1.0 + drop_pct / 100.0)
    return _benchmark_df(closes)


# ── utils.env ──


class TestFunnelConfig:
    def test_parse_int_env_reads_env(self, monkeypatch):
        from utils.env import parse_int_env

        monkeypatch.setenv("_TEST_INT", "42")
        assert parse_int_env("_TEST_INT", 0) == 42

    def test_parse_int_env_fallback_on_missing(self, monkeypatch):
        from utils.env import parse_int_env

        monkeypatch.delenv("_TEST_INT", raising=False)
        assert parse_int_env("_TEST_INT", 7) == 7

    def test_parse_int_env_handles_float_string(self, monkeypatch):
        from utils.env import parse_int_env

        monkeypatch.setenv("_TEST_INT", "5.0")
        assert parse_int_env("_TEST_INT", 0) == 5

    def test_parse_bool_truthy(self):
        from utils.env import parse_bool

        for val in ("1", "true", "True", "yes", "on"):
            assert parse_bool(val) is True, f"Expected True for {val!r}"

    def test_parse_bool_falsy(self):
        from utils.env import parse_bool

        for val in ("0", "false", "no", "off", ""):
            assert parse_bool(val) is False, f"Expected False for {val!r}"


# ── tools/report_builder ──


class TestReportBuilder:
    def test_extract_ops_codes_from_markdown_happy_path(self):
        from tools.report_parser import extract_ops_codes_from_markdown

        report = (
            "# \u5904\u4e8e\u8d77\u8df3\u677f\n"
            "- 600056 \u4e2d\u56fd\u533b\u836f\n"
            "- 300632 \u5149\u83c6\u80a1\u4efd\n"
            "# \u903b\u8f91\u7834\u4ea7\n"
            "- 000001 \u5e73\u5b89\u94f6\u884c\n"
        )
        allowed = {"600056", "300632", "000001"}
        result = extract_ops_codes_from_markdown(report, allowed)
        assert result == ["600056", "300632"]
        assert "000001" not in result

    def test_extract_ops_codes_empty_report(self):
        from tools.report_parser import extract_ops_codes_from_markdown

        assert extract_ops_codes_from_markdown("", set()) == []

    def test_try_parse_structured_report_none_on_empty(self):
        from tools.report_parser import try_parse_structured_report

        assert try_parse_structured_report("", set(), {}) is None

    def test_extract_json_block_strips_fences(self):
        from utils.json_text import extract_json_block

        raw = '```json\n{"key": "value"}\n```'
        result = extract_json_block(raw)
        assert result == '{"key": "value"}'

    def test_extract_json_block_plain_json(self):
        from utils.json_text import extract_json_block

        raw = '{"a": 1}'
        assert extract_json_block(raw) == '{"a": 1}'

    def test_extract_operation_pool_codes_happy_path(self):
        from tools.report_parser import extract_operation_pool_codes

        report = "# \u5904\u4e8e\u8d77\u8df3\u677f\n- 600056 \u4e2d\u56fd\u533b\u836f\n"
        codes = extract_operation_pool_codes(report, ["600056", "300632"])
        assert "600056" in codes

    def test_extract_operation_pool_codes_deduplicates(self):
        from tools.report_parser import extract_operation_pool_codes

        report = "# \u5904\u4e8e\u8d77\u8df3\u677f\n- 600056 A\n- 600056 B\n"
        codes = extract_operation_pool_codes(report, ["600056"])
        assert codes == ["600056"]

    def test_extract_operation_pool_springboards_reads_gate_line(self):
        from tools.report_parser import extract_operation_pool_springboards

        report = (
            "# \u5904\u4e8e\u8d77\u8df3\u677f\n"
            "603373 \u5b89\u90a6\u62a4\u536b\n"
            "\u6ee1\u8db3\u7684\u786c\u95e8\u69db\uff1a A+C\n"
            "Plan A: \u6b21\u65e5\u7f29\u91cf\u56de\u8e29\u3002\n"
            "\n"
            "301348 \u84dd\u7bad\u7535\u5b50\n"
            "\u6ee1\u8db3\u7684\u786c\u95e8\u69db\uff1a C + \u677f\u5757\u5171\u632f\u66ff\u4ee3A\n"
            "# \u903b\u8f91\u7834\u4ea7\n"
            "000001 \u5e73\u5b89\u94f6\u884c\n"
            "\u6ee1\u8db3\u7684\u786c\u95e8\u69db\uff1a A+B+C\n"
        )

        result = extract_operation_pool_springboards(report, ["603373", "301348", "000001"])

        assert result["603373"]["springboard_combo"] == "A+C"
        assert result["603373"]["springboard_a"] is True
        assert result["603373"]["springboard_c"] is True
        assert result["301348"]["springboard_combo"] == "A+C"
        assert result["301348"]["springboard_evidence"]["llm_hard_gates"] == "C + \u677f\u5757\u5171\u632f\u66ff\u4ee3A"
        assert "000001" not in result


# ── core.candidate_ranker ──


class TestCandidateRanker:
    def test_calc_close_return_pct_normal(self):
        from core.candidate_ranker import calc_close_return_pct

        s = pd.Series([100.0, 105.0, 110.0])
        result = calc_close_return_pct(s, lookback=1)
        assert result is not None
        assert abs(result - 4.76) < 0.1  # (110-105)/105 * 100

    def test_calc_close_return_pct_short_series(self):
        from core.candidate_ranker import calc_close_return_pct

        s = pd.Series([100.0])
        assert calc_close_return_pct(s, lookback=5) is None

    def test_calc_close_return_pct_zero_start(self):
        from core.candidate_ranker import calc_close_return_pct

        s = pd.Series([0.0, 10.0, 20.0])
        # lookback=1 → start=10, end=20 → 100%
        result = calc_close_return_pct(s, lookback=1)
        assert result is not None
        assert abs(result - 100.0) < 0.1

    def test_trigger_labels_is_dict(self):
        from core.candidate_ranker import TRIGGER_LABELS

        assert isinstance(TRIGGER_LABELS, dict)
        assert "sos" in TRIGGER_LABELS
        assert "spring" in TRIGGER_LABELS
        assert len(TRIGGER_LABELS) == 10

    def test_rank_l3_candidates_rewards_trigger_and_hot_sector(self):
        from core.candidate_ranker import rank_l3_candidates

        dates = pd.date_range("2026-01-01", periods=30, freq="D").strftime("%Y-%m-%d")
        df_map = {
            "000001": pd.DataFrame(
                {"date": dates, "close": [10.0 + i * 0.10 for i in range(30)], "volume": [1000] * 30}
            ),
            "000002": pd.DataFrame(
                {"date": dates, "close": [10.0 + i * 0.08 for i in range(30)], "volume": [1000] * 30}
            ),
            "000003": pd.DataFrame(
                {"date": dates, "close": [10.0 + i * 0.30 for i in range(30)], "volume": [1000] * 30}
            ),
        }

        ranked, score_map = rank_l3_candidates(
            ["000001", "000002", "000003"],
            df_map,
            {"000001": "热点行业", "000002": "冷门行业", "000003": "冷门行业"},
            {"sos": [("000001", 8.0)]},
            ["热点行业"],
        )

        assert ranked[0] == "000001"
        assert score_map["000001"] > score_map["000002"]

    def test_rank_l3_candidates_breaks_watch_score_ties_with_quality_inputs(self):
        from core.candidate_ranker import rank_l3_candidates

        dates = pd.date_range("2026-01-01", periods=30, freq="D").strftime("%Y-%m-%d")
        flat = pd.DataFrame({"date": dates, "close": [10.0] * 30, "volume": [1000] * 30})

        ranked, score_map = rank_l3_candidates(
            ["000003", "000002", "000001"],
            {"000001": flat.copy(), "000002": flat.copy(), "000003": flat.copy()},
            {"000001": "行业A", "000002": "行业A", "000003": "行业A"},
            {"sos": [("000002", 8.0), ("000003", 5.0), ("000001", 8.0)]},
            [],
        )

        assert score_map["000001"] == score_map["000002"]
        assert ranked == ["000001", "000002", "000003"]

    def test_rank_l3_candidates_penalizes_overextended_momentum(self):
        from core.candidate_ranker import rank_l3_candidates

        dates = pd.date_range("2026-01-01", periods=30, freq="D").strftime("%Y-%m-%d")
        healthy = [10.0] * 9 + [10.0 + i * 0.10 for i in range(21)]
        overheated = [10.0] * 9 + [10.0 + i * 0.55 for i in range(21)]
        df_map = {
            "000001": pd.DataFrame({"date": dates, "close": healthy, "volume": [1000] * 30}),
            "000002": pd.DataFrame({"date": dates, "close": overheated, "volume": [1000] * 30}),
        }

        ranked, score_map = rank_l3_candidates(
            ["000002", "000001"],
            df_map,
            {"000001": "行业A", "000002": "行业A"},
            {"sos": [("000001", 8.0), ("000002", 8.0)]},
            [],
        )

        assert ranked[0] == "000001"
        assert score_map["000001"] > score_map["000002"]


# ── tools/market_regime ──


class TestMarketRegime:
    def test_imports_callable(self):
        from tools.market_regime import (
            analyze_benchmark_and_tune_cfg,
            calc_amount_distribution_health,
            calc_market_breadth,
            calc_market_money_flow,
        )

        assert callable(analyze_benchmark_and_tune_cfg)
        assert callable(calc_amount_distribution_health)
        assert callable(calc_market_breadth)
        assert callable(calc_market_money_flow)

    def test_calc_market_breadth_empty(self):
        from tools.market_regime import calc_market_breadth

        result = calc_market_breadth({})
        assert result["ratio_pct"] is None
        assert result["sample_size"] == 0

    def test_calc_market_money_flow_detects_entry(self):
        from tools.market_regime import calc_market_money_flow

        df_map = {
            "000001": _money_flow_df(10.0, 11.0, 180_000_000),
            "000002": _money_flow_df(20.0, 21.0, 160_000_000),
            "000003": _money_flow_df(30.0, 29.7, 60_000_000),
        }
        result = calc_market_money_flow(df_map, {"delta_pct": 5.0})
        assert result["state"] == "主力进场"
        assert result["trend"] == "entry"
        assert result["amount_ratio_1_20"] > 1.1

    def test_calc_market_money_flow_detects_retreat(self):
        from tools.market_regime import calc_market_money_flow

        df_map = {
            "000001": _money_flow_df(10.0, 9.5, 180_000_000),
            "000002": _money_flow_df(20.0, 19.0, 160_000_000),
            "000003": _money_flow_df(30.0, 30.3, 50_000_000),
        }
        result = calc_market_money_flow(df_map, {"delta_pct": -6.0})
        assert result["state"] == "主力撤退"
        assert result["trend"] == "retreat"
        assert result["down_amount_yi"] > result["up_amount_yi"]

    def test_calc_amount_distribution_health_detects_thin_market(self):
        from tools.market_regime import calc_amount_distribution_health

        dates = pd.date_range("2026-01-01", periods=20, freq="D").strftime("%Y-%m-%d")
        df_map = {f"000{i:03d}": pd.DataFrame({"date": dates, "amount": [8_000_000.0] * 20}) for i in range(9)}
        df_map["000999"] = pd.DataFrame({"date": dates, "amount": [1_000_000_000.0] * 20})

        result = calc_amount_distribution_health(df_map, min_avg_amount_wan=5000.0)

        assert result["state"] == "thin"
        assert result["skewness"] > 2.0
        assert result["pass_ratio_pct"] < 35.0

    def test_market_regime_config_from_env_includes_pv_provider(self, monkeypatch):
        from workflows.market_regime_config import market_regime_config_from_env

        monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "efficiency")

        result = market_regime_config_from_env()

        assert result.pv_llm_provider == "efficiency"

    def test_holiday_grace_extends_when_money_flow_is_not_retreat(self, monkeypatch):
        import tools.market_regime as market_regime
        from core.wyckoff_engine import FunnelConfig

        monkeypatch.setattr(market_regime, "_generate_pv_outlook", lambda **_kwargs: "次日推演：测试")
        closes = list(pd.Series(range(220), dtype=float).map(lambda x: 100.0 + x * 0.2))
        bench = _benchmark_df(closes)
        prev_date = pd.to_datetime(bench.loc[len(bench) - 2, "date"])
        bench.loc[len(bench) - 1, "date"] = (prev_date + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        cfg = FunnelConfig()

        result = market_regime.analyze_benchmark_and_tune_cfg(
            bench,
            None,
            cfg,
            breadth={"ratio_pct": 70.0, "delta_pct": 5.0, "sample_size": 100},
            money_flow={"trend": "entry", "score": 25.0},
        )

        assert cfg.exit_holiday_grace_days == 2
        assert result["holiday_grace_dynamic"]["extended"] is True

    def test_market_pv_policy_shadow_structures_defensive_outlook(self):
        from core.wyckoff_engine import FunnelConfig
        from tools.market_regime import derive_market_pv_policy_shadow

        cfg = FunnelConfig()
        result = derive_market_pv_policy_shadow(
            outlook="次日推演：若放量跌破MA50，需转入防守；若缩量反弹，回避追高。",
            regime="RISK_ON",
            price_zone="多头上方",
            volume_state="放量",
            money_flow={"trend": "neutral"},
            cfg=cfg,
        )

        assert result["risk_bias"] == "defensive"
        assert result["conditions"][0]["if"] == "放量跌破MA50"
        assert result["funnel_config_overrides"]["rps_fast_min"] >= 80.0

    def test_breadth_risk_on_without_bull_structure_is_bear_rebound(self, monkeypatch):
        import tools.market_regime as market_regime
        from core.wyckoff_engine import FunnelConfig

        monkeypatch.setattr(market_regime, "_generate_pv_outlook", lambda **_kwargs: "次日推演：测试")
        closes = list(pd.Series(range(220), dtype=float).map(lambda x: 100.0 - x * 0.12))
        closes[-3:] = [75.0, 75.1, 75.2]

        cfg = FunnelConfig()
        result = market_regime.analyze_benchmark_and_tune_cfg(
            _benchmark_df(closes),
            None,
            cfg,
            breadth={"ratio_pct": 70.0, "delta_pct": 5.0, "sample_size": 100},
        )

        assert result["regime"] == "BEAR_REBOUND"
        assert result["bear_rebound_triggered"] is True
        assert cfg.rps_fast_min >= 80.0

    def test_breadth_risk_on_with_bull_structure_stays_risk_on(self, monkeypatch):
        import tools.market_regime as market_regime
        from core.wyckoff_engine import FunnelConfig

        monkeypatch.setattr(market_regime, "_generate_pv_outlook", lambda **_kwargs: "次日推演：测试")
        closes = list(pd.Series(range(220), dtype=float).map(lambda x: 100.0 + x * 0.2))

        result = market_regime.analyze_benchmark_and_tune_cfg(
            _benchmark_df(closes),
            None,
            FunnelConfig(),
            breadth={"ratio_pct": 70.0, "delta_pct": 5.0, "sample_size": 100},
        )

        assert result["regime"] == "RISK_ON"
        assert result["bear_rebound_triggered"] is False

    def test_single_index_drop_needs_confirmation_before_crash(self, monkeypatch):
        import tools.market_regime as market_regime
        from core.wyckoff_engine import FunnelConfig

        monkeypatch.setattr(market_regime, "_generate_pv_outlook", lambda **_kwargs: "次日推演：测试")

        result = market_regime.analyze_benchmark_and_tune_cfg(
            _benchmark_with_last_drop(-1.5),
            None,
            FunnelConfig(),
            breadth={"ratio_pct": 60.0, "delta_pct": -2.0, "sample_size": 100},
            money_flow={"trend": "neutral", "score": 0.0},
        )

        assert result["regime"] == "RISK_OFF"
        assert result["panic_reasons"] == []

    def test_two_index_drop_without_breadth_or_money_confirmation_stays_risk_off(self, monkeypatch):
        import tools.market_regime as market_regime
        from core.wyckoff_engine import FunnelConfig

        monkeypatch.setattr(market_regime, "_generate_pv_outlook", lambda **_kwargs: "次日推演：测试")

        result = market_regime.analyze_benchmark_and_tune_cfg(
            _benchmark_with_last_drop(-1.5),
            _benchmark_with_last_drop(-3.0),
            FunnelConfig(),
            breadth={"ratio_pct": 60.0, "delta_pct": -2.0, "sample_size": 100},
        )

        assert result["regime"] == "RISK_OFF"
        assert result["panic_reasons"] == []

    def test_index_drop_with_breadth_confirmation_confirms_crash(self, monkeypatch):
        import tools.market_regime as market_regime
        from core.wyckoff_engine import FunnelConfig

        monkeypatch.setattr(market_regime, "_generate_pv_outlook", lambda **_kwargs: "次日推演：测试")

        result = market_regime.analyze_benchmark_and_tune_cfg(
            _benchmark_with_last_drop(-1.5),
            _benchmark_with_last_drop(-3.0),
            FunnelConfig(),
            breadth={"ratio_pct": 12.0, "delta_pct": -25.0, "sample_size": 100},
        )

        assert result["regime"] == "CRASH"
        assert any("main_day_drop" in item for item in result["panic_reasons"])
        assert any("breadth_" in item for item in result["panic_reasons"])

    def test_money_flow_retreat_confirms_crash(self, monkeypatch):
        import tools.market_regime as market_regime
        from core.wyckoff_engine import FunnelConfig

        monkeypatch.setattr(market_regime, "_generate_pv_outlook", lambda **_kwargs: "次日推演：测试")

        result = market_regime.analyze_benchmark_and_tune_cfg(
            _benchmark_with_last_drop(-1.5),
            None,
            FunnelConfig(),
            breadth={"ratio_pct": 60.0, "delta_pct": -2.0, "sample_size": 100},
            money_flow={"trend": "retreat", "score": -25.0},
        )

        assert result["regime"] == "CRASH"
        assert any("money_flow_retreat" in item for item in result["panic_reasons"])


# ── tools/data_fetcher ──


class TestDataFetcher:
    def test_latest_trade_date_from_hist_empty(self):
        from tools.data_fetcher import latest_trade_date_from_hist

        assert latest_trade_date_from_hist(pd.DataFrame()) is None

    def test_latest_trade_date_from_hist_no_date_col(self):
        from tools.data_fetcher import latest_trade_date_from_hist

        df = pd.DataFrame({"close": [1, 2, 3]})
        assert latest_trade_date_from_hist(df) is None

    def test_latest_trade_date_from_hist_valid(self):
        from tools.data_fetcher import latest_trade_date_from_hist

        df = pd.DataFrame({"date": ["2025-01-01", "2025-01-02"]})
        result = latest_trade_date_from_hist(df)
        assert result == date(2025, 1, 2)

    def test_tickflow_batch_partial_keeps_available_frames(self, monkeypatch):
        import tools.tickflow_batch_fetcher as batcher

        class FakeTickFlowClient:
            def __init__(self, api_key: str) -> None:
                self.api_key = api_key

            def get_klines_batch(self, *args, **kwargs):
                return {
                    "000001.SZ": pd.DataFrame(
                        {
                            "date": ["2025-01-01", "2025-01-02"],
                            "open": [10.0, 10.1],
                            "high": [10.5, 10.6],
                            "low": [9.8, 9.9],
                            "close": [10.2, 10.3],
                            "volume": [1000, 1100],
                        }
                    )
                }

        window = SimpleNamespace(start_trade_date=date(2025, 1, 1), end_trade_date=date(2025, 1, 2))
        monkeypatch.setenv("TICKFLOW_API_KEY", "dummy")
        monkeypatch.setattr(batcher, "TICKFLOW_BATCH_ENABLED", True)
        monkeypatch.setattr(batcher, "TickFlowClient", FakeTickFlowClient)

        result = batcher.fetch_tickflow_daily_batch(
            ["000001", "000002"],
            window,
            enforce_target_trade_date=False,
            batch_size=200,
            batch_sleep=0,
        )

        assert result is not None
        df_map, stats = result
        assert list(df_map) == ["000001"]
        assert stats["fetch_ok"] == 1
        assert stats["fetch_fail"] == 1

    def test_fetch_hist_direct_source_bypasses_cached_repository(self, monkeypatch):
        import integrations.data_source as data_source
        import integrations.fetch_a_share_csv as fetch_csv
        import tools.ohlcv_fallback_fetcher as fallback_fetcher

        calls: list[dict] = []

        def fake_source(**kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                {
                    "日期": ["2026-05-12", "2026-05-13"],
                    "开盘": [10.0, 10.5],
                    "最高": [10.2, 10.8],
                    "最低": [9.9, 10.4],
                    "收盘": [10.1, 10.7],
                    "成交量": [1000, 1200],
                    "成交额": [10100, 12840],
                    "涨跌幅": [0.0, 5.94],
                    "换手率": [pd.NA, pd.NA],
                    "振幅": [pd.NA, pd.NA],
                }
            )

        def cached_fetch(**kwargs):
            raise AssertionError(f"should bypass cached repository: {kwargs}")

        monkeypatch.setattr(data_source, "fetch_stock_hist", fake_source)
        monkeypatch.setattr(fetch_csv, "fetch_hist", cached_fetch)
        window = SimpleNamespace(start_trade_date=date(2026, 5, 12), end_trade_date=date(2026, 5, 13))

        result = fallback_fetcher._fetch_hist("000001", window, "qfq", direct_source=True)

        assert result["close"].tolist() == [10.1, 10.7]
        assert calls == [
            {
                "symbol": "000001",
                "start": date(2026, 5, 12),
                "end": date(2026, 5, 13),
                "adjust": "qfq",
            }
        ]

    def test_append_spot_bar_zero_fallback_avoids_turnover_pollution(self, monkeypatch):
        import tools.spot_patch as spot_patch

        target = pd.Timestamp.now(tz=spot_patch.CN_TZ).date()
        frame = pd.DataFrame(
            {
                "date": [(target - timedelta(days=1)).isoformat()],
                "open": [10.0],
                "high": [10.4],
                "low": [9.8],
                "close": [10.0],
                "volume": [12345.0],
                "amount": [123450.0],
            }
        )
        monkeypatch.setattr(
            spot_patch,
            "fetch_stock_spot_snapshot",
            lambda *_args, **_kwargs: {
                "open": 10.2,
                "high": 10.5,
                "low": 10.1,
                "close": 10.4,
                "turnover_unit_ok": 0.0,
            },
        )

        patched, ok = spot_patch.append_spot_bar_if_needed(
            "000001", frame, target, env_prefix="TEST", zero_fallback=True
        )

        assert ok is True
        assert patched.iloc[-1]["date"] == target.isoformat()
        assert patched.iloc[-1]["volume"] == 0.0
        assert patched.iloc[-1]["amount"] == 0.0
        assert round(float(patched.iloc[-1]["pct_chg"]), 2) == 4.0

    def test_fetch_all_ohlcv_thread_fallback_counts_success_and_failure(self, monkeypatch):
        import tools.ohlcv_fallback_fetcher as fallback_fetcher
        import tools.tickflow_batch_fetcher as batcher

        def fake_fetch(sym, *_args):
            if sym == "000001":
                return sym, pd.DataFrame({"date": ["2026-05-13"], "close": [10.0]})
            return sym, None

        monkeypatch.setattr(batcher, "fetch_tickflow_daily_batch", lambda **_kwargs: None)
        monkeypatch.setattr(fallback_fetcher, "fetch_one_with_retry_thread", fake_fetch)
        window = SimpleNamespace(start_trade_date=date(2026, 5, 12), end_trade_date=date(2026, 5, 13))

        df_map, stats = fallback_fetcher.fetch_ohlcv_fallback(
            ["000001", "000002"],
            window,
            enforce_target_trade_date=True,
            batch_size=2,
            max_workers=1,
            batch_timeout=10,
            batch_sleep=0,
            executor_mode="thread",
            direct_source=False,
        )

        assert list(df_map) == ["000001"]
        assert stats["fetch_ok"] == 1
        assert stats["fetch_fail"] == 1


# ── tools/symbol_pool ──


class TestSymbolPool:
    def test_load_stock_name_map_callable(self):
        from tools.symbol_pool import load_stock_name_map

        assert callable(load_stock_name_map)

    def test_default_pool_includes_star_board(self, monkeypatch):
        from tools import symbol_pool

        boards = {
            "main": [{"code": "000001", "name": "平安银行"}],
            "chinext": [{"code": "300001", "name": "特锐德"}],
            "star": [{"code": "688001", "name": "华兴源创"}],
        }

        monkeypatch.delenv("FUNNEL_POOL_MODE", raising=False)
        monkeypatch.delenv("FUNNEL_POOL_BOARD", raising=False)
        monkeypatch.delenv("FUNNEL_POOL_LIMIT_COUNT", raising=False)
        monkeypatch.setattr(symbol_pool, "get_stocks_by_board", lambda board: boards[board])

        symbols, name_map, stats = symbol_pool.resolve_symbol_pool_from_env()

        assert symbols == ["000001", "300001", "688001"]
        assert name_map["688001"] == "华兴源创"
        assert stats["pool_star"] == 1

    def test_board_pool_accepts_star(self, monkeypatch):
        from tools import symbol_pool

        monkeypatch.setenv("FUNNEL_POOL_MODE", "board")
        monkeypatch.setenv("FUNNEL_POOL_BOARD", "star")
        monkeypatch.delenv("FUNNEL_POOL_LIMIT_COUNT", raising=False)
        monkeypatch.setattr(
            symbol_pool,
            "get_stocks_by_board",
            lambda board: [{"code": "688001", "name": "华兴源创"}] if board == "star" else [],
        )

        symbols, _name_map, stats = symbol_pool.resolve_symbol_pool_from_env()

        assert symbols == ["688001"]
        assert stats["pool_star"] == 1

    def test_explicit_board_pool_ignores_env_mode(self, monkeypatch):
        from tools import symbol_pool

        monkeypatch.setenv("FUNNEL_POOL_MODE", "manual")
        monkeypatch.setenv("FUNNEL_POOL_MANUAL_SYMBOLS", "000001")
        monkeypatch.setattr(
            symbol_pool,
            "get_stocks_by_board",
            lambda board: [{"code": "688001", "name": "华兴源创"}] if board == "star" else [],
        )

        symbols, _name_map, stats = symbol_pool.resolve_symbol_pool(pool_mode="board", board_name="star")

        assert symbols == ["688001"]
        assert stats["pool_mode"] == "board"
        assert stats["pool_star"] == 1

    def test_main_chinext_alias_uses_all_target_boards(self, monkeypatch):
        from tools import symbol_pool

        boards = {
            "all": [
                {"code": "000001", "name": "平安银行"},
                {"code": "300001", "name": "特锐德"},
                {"code": "688001", "name": "华兴源创"},
            ],
            "main": [{"code": "000001", "name": "平安银行"}],
            "chinext": [{"code": "300001", "name": "特锐德"}],
            "star": [{"code": "688001", "name": "华兴源创"}],
        }

        monkeypatch.setenv("FUNNEL_POOL_MODE", "board")
        monkeypatch.setenv("FUNNEL_POOL_BOARD", "main_chinext")
        monkeypatch.delenv("FUNNEL_POOL_LIMIT_COUNT", raising=False)
        monkeypatch.setattr(symbol_pool, "get_stocks_by_board", lambda board: boards[board])

        symbols, _name_map, stats = symbol_pool.resolve_symbol_pool_from_env()

        assert symbols == ["000001", "300001", "688001"]
        assert stats["pool_main"] == 1
        assert stats["pool_chinext"] == 1
        assert stats["pool_star"] == 1

    def test_screen_stocks_accepts_mcp_main_chinext_alias(self, monkeypatch):
        from agents import screen_tools

        captured_kwargs = {}
        fake_pipeline = ModuleType("workflows.wyckoff_funnel")

        def fake_run_funnel(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return True, [], {}, {"metrics": {}, "triggers": {}, "name_map": {}}

        fake_pipeline.run = fake_run_funnel
        monkeypatch.setitem(sys.modules, "workflows.wyckoff_funnel", fake_pipeline)
        monkeypatch.setattr(screen_tools, "ensure_tushare_token", lambda tool_context: None)
        monkeypatch.setenv("FUNNEL_POOL_MODE", "manual")
        monkeypatch.setenv("FUNNEL_POOL_BOARD", "chinext")
        monkeypatch.setenv("FUNNEL_EXECUTOR_MODE", "process")

        result = screen_tools.screen_stocks(board="main_chinext")

        assert "error" not in result
        assert captured_kwargs["pool_board"] == "all"
        assert captured_kwargs["executor_mode"] == "thread"
        assert os.environ["FUNNEL_POOL_MODE"] == "manual"
        assert os.environ["FUNNEL_POOL_BOARD"] == "chinext"
        assert os.environ["FUNNEL_EXECUTOR_MODE"] == "process"
