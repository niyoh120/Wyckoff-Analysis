"""tools/ 层单元测试 — 测试 Phase 2 提取的纯逻辑 Tool 函数。"""

from __future__ import annotations

import os
import sys
from datetime import date
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


# ── tools/funnel_config ──


class TestFunnelConfig:
    def test_parse_int_env_reads_env(self, monkeypatch):
        from tools.funnel_config import parse_int_env

        monkeypatch.setenv("_TEST_INT", "42")
        assert parse_int_env("_TEST_INT", 0) == 42

    def test_parse_int_env_fallback_on_missing(self, monkeypatch):
        from tools.funnel_config import parse_int_env

        monkeypatch.delenv("_TEST_INT", raising=False)
        assert parse_int_env("_TEST_INT", 7) == 7

    def test_parse_int_env_handles_float_string(self, monkeypatch):
        from tools.funnel_config import parse_int_env

        monkeypatch.setenv("_TEST_INT", "5.0")
        assert parse_int_env("_TEST_INT", 0) == 5

    def test_parse_bool_truthy(self):
        from tools.funnel_config import parse_bool

        for val in ("1", "true", "True", "yes", "on"):
            assert parse_bool(val) is True, f"Expected True for {val!r}"

    def test_parse_bool_falsy(self):
        from tools.funnel_config import parse_bool

        for val in ("0", "false", "no", "off", ""):
            assert parse_bool(val) is False, f"Expected False for {val!r}"


# ── tools/report_builder ──


class TestReportBuilder:
    def test_extract_ops_codes_from_markdown_happy_path(self):
        from tools.report_builder import _extract_ops_codes_from_markdown

        report = (
            "# \u5904\u4e8e\u8d77\u8df3\u677f\n"
            "- 600056 \u4e2d\u56fd\u533b\u836f\n"
            "- 300632 \u5149\u83c6\u80a1\u4efd\n"
            "# \u903b\u8f91\u7834\u4ea7\n"
            "- 000001 \u5e73\u5b89\u94f6\u884c\n"
        )
        allowed = {"600056", "300632", "000001"}
        result = _extract_ops_codes_from_markdown(report, allowed)
        assert result == ["600056", "300632"]
        assert "000001" not in result

    def test_extract_ops_codes_empty_report(self):
        from tools.report_builder import _extract_ops_codes_from_markdown

        assert _extract_ops_codes_from_markdown("", set()) == []

    def test_try_parse_structured_report_none_on_empty(self):
        from tools.report_builder import _try_parse_structured_report

        assert _try_parse_structured_report("", set(), {}) is None

    def test_extract_json_block_strips_fences(self):
        from tools.report_builder import _extract_json_block

        raw = '```json\n{"key": "value"}\n```'
        result = _extract_json_block(raw)
        assert result == '{"key": "value"}'

    def test_extract_json_block_plain_json(self):
        from tools.report_builder import _extract_json_block

        raw = '{"a": 1}'
        assert _extract_json_block(raw) == '{"a": 1}'

    def test_extract_operation_pool_codes_happy_path(self):
        from tools.report_builder import extract_operation_pool_codes

        report = "# \u5904\u4e8e\u8d77\u8df3\u677f\n- 600056 \u4e2d\u56fd\u533b\u836f\n"
        codes = extract_operation_pool_codes(report, ["600056", "300632"])
        assert "600056" in codes

    def test_extract_operation_pool_codes_deduplicates(self):
        from tools.report_builder import extract_operation_pool_codes

        report = "# \u5904\u4e8e\u8d77\u8df3\u677f\n- 600056 A\n- 600056 B\n"
        codes = extract_operation_pool_codes(report, ["600056"])
        assert codes == ["600056"]

    def test_extract_operation_pool_springboards_reads_gate_line(self):
        from tools.report_builder import extract_operation_pool_springboards

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


# ── tools/candidate_ranker ──


class TestCandidateRanker:
    def test_calc_close_return_pct_normal(self):
        from tools.candidate_ranker import calc_close_return_pct

        s = pd.Series([100.0, 105.0, 110.0])
        result = calc_close_return_pct(s, lookback=1)
        assert result is not None
        assert abs(result - 4.76) < 0.1  # (110-105)/105 * 100

    def test_calc_close_return_pct_short_series(self):
        from tools.candidate_ranker import calc_close_return_pct

        s = pd.Series([100.0])
        assert calc_close_return_pct(s, lookback=5) is None

    def test_calc_close_return_pct_zero_start(self):
        from tools.candidate_ranker import calc_close_return_pct

        s = pd.Series([0.0, 10.0, 20.0])
        # lookback=1 → start=10, end=20 → 100%
        result = calc_close_return_pct(s, lookback=1)
        assert result is not None
        assert abs(result - 100.0) < 0.1

    def test_trigger_labels_is_dict(self):
        from tools.candidate_ranker import TRIGGER_LABELS

        assert isinstance(TRIGGER_LABELS, dict)
        assert "sos" in TRIGGER_LABELS
        assert "spring" in TRIGGER_LABELS
        assert len(TRIGGER_LABELS) == 6


# ── tools/market_regime ──


class TestMarketRegime:
    def test_imports_callable(self):
        from tools.market_regime import analyze_benchmark_and_tune_cfg, calc_market_breadth, calc_market_money_flow

        assert callable(analyze_benchmark_and_tune_cfg)
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
        import tools.data_fetcher as dfetcher

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
        monkeypatch.setattr(dfetcher, "TICKFLOW_BATCH_ENABLED", True)
        monkeypatch.setattr(dfetcher, "TickFlowClient", FakeTickFlowClient)

        result = dfetcher._fetch_all_ohlcv_tickflow_batch(["000001", "000002"], window, False, 200, 0)

        assert result is not None
        df_map, stats = result
        assert list(df_map) == ["000001"]
        assert stats["fetch_ok"] == 1
        assert stats["fetch_fail"] == 1

    def test_fetch_hist_direct_source_bypasses_cached_repository(self, monkeypatch):
        import integrations.data_source as data_source
        import integrations.fetch_a_share_csv as fetch_csv
        import tools.data_fetcher as dfetcher

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
        monkeypatch.setattr(fetch_csv, "_fetch_hist", cached_fetch)
        window = SimpleNamespace(start_trade_date=date(2026, 5, 12), end_trade_date=date(2026, 5, 13))

        result = dfetcher._fetch_hist("000001", window, "qfq", direct_source=True)

        assert result["close"].tolist() == [10.1, 10.7]
        assert calls == [
            {
                "symbol": "000001",
                "start": date(2026, 5, 12),
                "end": date(2026, 5, 13),
                "adjust": "qfq",
            }
        ]


# ── tools/symbol_pool ──


class TestSymbolPool:
    def test_stock_name_map_callable(self):
        from tools.symbol_pool import _stock_name_map

        assert callable(_stock_name_map)

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
        from agents import chat_tools

        captured_env = {}
        fake_pipeline = ModuleType("scripts.wyckoff_funnel")

        def fake_run_funnel(*args, **kwargs):
            captured_env["mode"] = os.environ.get("FUNNEL_POOL_MODE")
            captured_env["board"] = os.environ.get("FUNNEL_POOL_BOARD")
            captured_env["executor"] = os.environ.get("FUNNEL_EXECUTOR_MODE")
            return True, [], {}, {"metrics": {}, "triggers": {}, "name_map": {}}

        fake_pipeline.run = fake_run_funnel
        monkeypatch.setitem(sys.modules, "scripts.wyckoff_funnel", fake_pipeline)
        monkeypatch.setattr(chat_tools, "_ensure_tushare_token", lambda tool_context: None)
        monkeypatch.setenv("FUNNEL_POOL_MODE", "manual")
        monkeypatch.setenv("FUNNEL_POOL_BOARD", "chinext")
        monkeypatch.setenv("FUNNEL_EXECUTOR_MODE", "process")

        result = chat_tools.screen_stocks(board="main_chinext")

        assert "error" not in result
        assert captured_env == {"mode": "board", "board": "all", "executor": "thread"}
        assert os.environ["FUNNEL_POOL_MODE"] == "manual"
        assert os.environ["FUNNEL_POOL_BOARD"] == "chinext"
        assert os.environ["FUNNEL_EXECUTOR_MODE"] == "process"


# ── core/strategy bridge ──


class TestStrategyBridge:
    def test_bridge_exports_are_importable(self):
        from core.strategy import run_step4

        assert callable(run_step4)
