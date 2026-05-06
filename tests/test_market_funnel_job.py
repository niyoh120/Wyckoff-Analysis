from __future__ import annotations

import json

import pandas as pd

from scripts.market_funnel_job import run_market_funnel


def _daily_frame(rows: int = 230) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = pd.Series(range(rows), dtype="float64") * 0.2 + 100.0
    open_ = close - 0.5
    high = close + 1.0
    low = close - 1.0
    volume = pd.Series([1_000_000 + i * 1000 for i in range(rows)], dtype="float64")
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": close * volume,
            "pct_chg": close.pct_change().fillna(0.0) * 100.0,
        }
    )


class FakeTickFlowClient:
    def __init__(self) -> None:
        self.kline_batches: list[list[str]] = []

    def get_quotes(self, symbols=None, *, universes=None):
        assert symbols is None
        assert universes == ["HK_Equity"]
        return {
            "00700.HK": {
                "symbol": "00700.HK",
                "last_price": 350.0,
                "amount": 9_000_000.0,
                "ext": {"name": "Tencent", "change_pct": 0.01},
            },
            "00005.HK": {
                "symbol": "00005.HK",
                "last_price": 65.0,
                "amount": 8_000_000.0,
                "ext": {"name": "HSBC", "change_pct": -0.005},
            },
            "09999.HK": {"symbol": "09999.HK", "last_price": 0.0, "amount": 10_000_000.0},
        }

    def get_klines_batch(self, symbols, *, period, count, adjust):
        self.kline_batches.append(list(symbols))
        assert period == "1d"
        assert count == 230
        assert adjust == "forward"
        return {symbol: _daily_frame() for symbol in symbols}


def test_run_market_funnel_uses_quote_prefilter_and_batch_fetch(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_FUNNEL_MAX_SYMBOLS", "2")
    monkeypatch.setenv("MARKET_FUNNEL_KLINE_COUNT", "230")
    monkeypatch.setenv("MARKET_FUNNEL_KLINE_BATCH_SIZE", "1")
    monkeypatch.setenv("MARKET_FUNNEL_KLINE_BATCH_SLEEP", "0")
    monkeypatch.setenv("MARKET_FUNNEL_MIN_QUOTE_AMOUNT", "0")
    monkeypatch.setenv("MARKET_FUNNEL_MIN_HISTORY_ROWS", "220")
    output = tmp_path / "hk_result.json"
    client = FakeTickFlowClient()

    result = run_market_funnel("hk", output=str(output), client=client)

    assert result["ok"] is True
    assert result["market"] == "hk"
    assert result["quote_count"] == 3
    assert result["selected_count"] == 2
    assert result["fetched_count"] == 2
    assert client.kline_batches == [["00700.HK"], ["00005.HK"]]
    assert json.loads(output.read_text(encoding="utf-8"))["limits"]["kline_batch_size"] == 1
