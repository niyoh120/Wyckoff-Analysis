from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

import integrations.data_source_baostock as provider
from integrations.data_source_format import STOCK_HIST_COLUMNS


class _FakeResult:
    fields = ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"]
    error_code = "0"
    error_msg = ""

    def __init__(self) -> None:
        self._rows = [["2026-06-01", "10", "10.5", "9.8", "10.2", "1000", "10200", "2.0"]]
        self._idx = -1

    def next(self) -> bool:
        self._idx += 1
        return self._idx < len(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows[self._idx]


def _reset_provider_state(monkeypatch) -> None:
    monkeypatch.setattr(provider, "_LOGGED", False)
    monkeypatch.setattr(provider, "_EXIT_HOOKED", False)
    monkeypatch.setattr(provider, "_MODULE", None)
    monkeypatch.setattr(provider, "_CONSEC_FAILS", 0)
    monkeypatch.setattr(provider, "_CIRCUIT_OPEN", False)
    monkeypatch.setattr(provider, "_CIRCUIT_NOTE", "")


def test_fetch_stock_baostock_normalizes_rows_and_uses_exchange_prefix(monkeypatch) -> None:
    _reset_provider_state(monkeypatch)
    captured: dict[str, object] = {}

    def fake_query(code: str, fields: str, **kwargs):
        captured.update({"code": code, "fields": fields, **kwargs})
        return _FakeResult()

    fake_module = SimpleNamespace(
        login=lambda: SimpleNamespace(error_code="0", error_msg=""),
        logout=lambda: None,
        query_history_k_data_plus=fake_query,
    )
    monkeypatch.setitem(sys.modules, "baostock", fake_module)
    monkeypatch.setattr(provider.atexit, "register", lambda *_args, **_kwargs: None)

    out = provider.fetch_stock_baostock("600519", "20260601", "20260602")

    assert tuple(out.columns) == STOCK_HIST_COLUMNS
    assert captured["code"] == "sh.600519"
    assert captured["start_date"] == "2026-06-01"
    assert captured["end_date"] == "2026-06-02"
    assert out.iloc[0]["日期"] == "2026-06-01"
    assert float(out.iloc[0]["收盘"]) == 10.2
    assert pd.isna(out.iloc[0]["换手率"])


def test_baostock_circuit_opens_after_configured_failures(monkeypatch) -> None:
    _reset_provider_state(monkeypatch)
    monkeypatch.setattr(provider, "_CIRCUIT_THRESHOLD", 2)

    provider.baostock_mark_failure("first")
    assert provider.baostock_circuit_state() == (False, "")

    provider.baostock_mark_failure("second")
    opened, note = provider.baostock_circuit_state()
    assert opened is True
    assert "consecutive_failures=2" in note
