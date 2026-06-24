from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import integrations.data_source_tickflow as provider
from integrations.data_source_format import STOCK_HIST_COLUMNS
from integrations.tickflow_notice import TICKFLOW_LIMIT_HINT


def test_fetch_stock_tickflow_uses_client_window_and_normalizes_frame(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_klines(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame(
            {
                "date": ["2026-06-01"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "prev_close": [10.0],
                "volume": [1000],
                "amount": [10200],
            }
        )

    monkeypatch.setattr(provider, "_CLIENT_READY", True)
    monkeypatch.setattr(provider, "_CLIENT", SimpleNamespace(get_klines=fake_get_klines))

    out = provider.fetch_stock_tickflow("600519", "20260601", "20260601", "qfq")

    assert tuple(out.columns) == STOCK_HIST_COLUMNS
    assert captured["symbol"] == "600519"
    assert captured["period"] == "1d"
    assert captured["adjust"] == "forward"
    assert float(out.iloc[0]["收盘"]) == 10.2


def test_attach_tickflow_limit_notices_deduplicates_attrs(monkeypatch) -> None:
    monkeypatch.setattr(provider, "_LIMIT_NOTICE_EMITTED", False)
    df = pd.DataFrame({"收盘": [10.0]})

    out = provider.attach_tickflow_limit_notices(df, [TICKFLOW_LIMIT_HINT, "", TICKFLOW_LIMIT_HINT])

    assert out is df
    assert out.attrs["tickflow_limit_hint"] == TICKFLOW_LIMIT_HINT
    assert out.attrs["tickflow_limit_hints"] == [TICKFLOW_LIMIT_HINT]
