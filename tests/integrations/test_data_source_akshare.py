from __future__ import annotations

import sys
from http.client import RemoteDisconnected
from types import ModuleType

import pandas as pd

import integrations.data_source_akshare as provider


def test_fetch_stock_akshare_retries_transient_disconnect_and_normalizes_date(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    fake_ak = ModuleType("akshare")

    def fake_hist(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RemoteDisconnected("remote end closed connection")
        return pd.DataFrame(
            {
                "日期": ["20260601"],
                "开盘": [10.0],
                "最高": [10.5],
                "最低": [9.8],
                "收盘": [10.2],
            }
        )

    fake_ak.stock_zh_a_hist = fake_hist
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    monkeypatch.setattr(provider, "_RETRY_TIMES", 2)
    monkeypatch.setattr(provider, "_RETRY_SLEEP_SECONDS", 0.0)

    out = provider.fetch_stock_akshare("600519", "20260601", "20260602", "qfq")

    assert len(calls) == 2
    assert calls[0]["symbol"] == "600519"
    assert calls[0]["period"] == "daily"
    assert calls[0]["adjust"] == "qfq"
    assert out.iloc[0]["日期"] == "2026-06-01"
