from __future__ import annotations

from datetime import date

import pandas as pd

from agents import diagnosis_tools


def test_analyze_stock_price_returns_price_records(monkeypatch) -> None:
    rows = pd.DataFrame(
        [
            {
                "日期": "2026-06-18",
                "开盘": 10.0,
                "最高": 10.5,
                "最低": 9.9,
                "收盘": 10.2,
                "成交量": 1000,
                "涨跌幅": 2.0,
            }
        ]
    )
    rows.attrs["tickflow_limit_hint"] = "TickFlow fallback"

    def fake_get_stock_hist(code: str, start_date: date, end_date: date):
        assert code == "000001"
        assert start_date <= end_date
        return rows

    monkeypatch.setattr(diagnosis_tools, "ensure_tushare_token", lambda _ctx: None)
    monkeypatch.setattr("integrations.stock_hist_repository.get_stock_hist", fake_get_stock_hist)

    result = diagnosis_tools.analyze_stock("000001", mode="price", days=1)

    assert result["data_status"] == "ok"
    assert result["latest_close"] == 10.2
    assert result["data"][0]["close"] == 10.2
    assert result["tickflow_limit_hint"] == "TickFlow fallback"


def test_analyze_stock_price_sanitizes_bad_ohlcv(monkeypatch) -> None:
    rows = pd.DataFrame(
        [
            {
                "日期": "2026-06-18",
                "开盘": "bad",
                "最高": float("inf"),
                "最低": float("-inf"),
                "收盘": float("nan"),
                "成交量": "bad",
                "涨跌幅": float("nan"),
            }
        ]
    )

    monkeypatch.setattr(diagnosis_tools, "ensure_tushare_token", lambda _ctx: None)
    monkeypatch.setattr("integrations.stock_hist_repository.get_stock_hist", lambda *_args, **_kwargs: rows)

    result = diagnosis_tools.analyze_stock("000001", mode="price", days=1)

    assert result["latest_close"] is None
    assert result["data"][0] == {
        "date": "2026-06-18",
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume": 0,
        "pct_chg": None,
    }


def test_analyze_stock_rejects_unknown_mode(monkeypatch) -> None:
    monkeypatch.setattr(diagnosis_tools, "ensure_tushare_token", lambda _ctx: None)

    result = diagnosis_tools.analyze_stock("000001", mode="x")

    assert "mode 参数无效" in result["error"]
