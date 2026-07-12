from __future__ import annotations

import sys
from types import ModuleType

import pandas as pd
import pytest

import integrations.data_source_tushare as provider
from integrations.data_source_format import STOCK_HIST_COLUMNS


class _FakePro:
    def daily(self, **_kwargs):
        return pd.DataFrame()


def test_fetch_stock_tushare_normalizes_pro_bar_units(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_ts = ModuleType("tushare")

    def fake_pro_bar(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame(
            {
                "trade_date": ["20260601"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "vol": [100],
                "amount": [120],
                "pct_chg": [2.0],
            }
        )

    fake_ts.pro_bar = fake_pro_bar
    monkeypatch.setitem(sys.modules, "tushare", fake_ts)
    monkeypatch.setattr("integrations.tushare_client.get_pro", lambda: _FakePro())
    monkeypatch.setattr("integrations.tushare_client.wait_for_rate_limit", lambda: None)

    out = provider.fetch_stock_tushare("600519", "20260601", "20260602")

    assert tuple(out.columns) == STOCK_HIST_COLUMNS
    assert isinstance(captured.pop("api"), _FakePro)
    assert captured == {"ts_code": "600519.SH", "adj": "qfq", "start_date": "20260601", "end_date": "20260602"}
    assert out.iloc[0]["日期"] == "2026-06-01"
    assert float(out.iloc[0]["成交量"]) == 10000
    assert float(out.iloc[0]["成交额"]) == 120000


def test_fetch_stock_tushare_skips_when_token_missing(monkeypatch) -> None:
    monkeypatch.setattr("integrations.tushare_client.get_pro", lambda: None)

    with pytest.raises(RuntimeError, match="token_missing"):
        provider.fetch_stock_tushare("600519", "20260601", "20260602")
