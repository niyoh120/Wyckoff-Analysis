from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

import integrations.data_source_efinance as provider
from integrations.data_source_format import STOCK_HIST_COLUMNS


def _install_fake_efinance(monkeypatch, quote_result) -> ModuleType:
    fake_pkg = ModuleType("efinance")
    fake_pkg.__path__ = []
    fake_config = ModuleType("efinance.config")

    def fake_quote_history(symbol: str, **kwargs):
        fake_quote_history.calls.append((symbol, kwargs))
        return quote_result

    fake_quote_history.calls = []
    fake_pkg.config = fake_config
    fake_pkg.stock = SimpleNamespace(get_quote_history=fake_quote_history)
    monkeypatch.setitem(sys.modules, "efinance", fake_pkg)
    monkeypatch.setitem(sys.modules, "efinance.config", fake_config)
    return fake_pkg


def test_fetch_stock_efinance_normalizes_quote_history_and_cache_config(monkeypatch) -> None:
    raw = pd.DataFrame(
        {
            "股票日期": ["2026-06-01"],
            "开盘价": [10.0],
            "最高价": [10.5],
            "最低价": [9.8],
            "收盘价": [10.2],
            "成交量": [1000],
            "成交额": [10200],
            "涨跌幅": [2.0],
        }
    )
    fake_pkg = _install_fake_efinance(monkeypatch, {"600519": raw})

    out = provider.fetch_stock_efinance("600519", "20260601", "20260602")

    calls = fake_pkg.stock.get_quote_history.calls
    assert calls == [("600519", {"beg": "20260601", "end": "20260602", "klt": 101, "fqt": 1})]
    assert tuple(out.columns) == STOCK_HIST_COLUMNS
    assert out.iloc[0]["日期"] == "2026-06-01"
    assert float(out.iloc[0]["收盘"]) == 10.2
    assert "efinance-cache" in str(fake_pkg.config.DATA_DIR)
    assert str(fake_pkg.config.SEARCH_RESULT_CACHE_PATH).endswith("search-cache.json")


def test_fetch_stock_efinance_rejects_empty_payload(monkeypatch) -> None:
    _install_fake_efinance(monkeypatch, {"600519": pd.DataFrame()})

    with pytest.raises(RuntimeError, match="efinance empty"):
        provider.fetch_stock_efinance("600519", "20260601", "20260602")
