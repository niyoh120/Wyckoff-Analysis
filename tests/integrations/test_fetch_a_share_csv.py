from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

import pytest

import integrations.fetch_a_share_csv as fetch_csv


def _use_tmp_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fetch_csv, "_cache_path", lambda filename: tmp_path / filename)


def _write_json(path: Path, payload: object, *, age_seconds: int = 0) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if age_seconds:
        ts = time.time() - age_seconds
        os.utime(path, (ts, ts))


def test_trade_dates_uses_fresh_cache_without_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    _write_json(tmp_path / "trade_dates_cache.json", ["2026-06-18", "bad", "2026-06-17"])

    def _fail_fetch(cache_path: Path):
        raise AssertionError(f"unexpected network fetch: {cache_path}")

    monkeypatch.setattr(fetch_csv, "_fetch_trade_dates_from_sources", _fail_fetch)

    assert fetch_csv._trade_dates() == [date(2026, 6, 17), date(2026, 6, 18)]


def test_trade_dates_returns_stale_cache_when_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "trade_dates_cache.json",
        ["2026-06-13", "2026-06-16"],
        age_seconds=fetch_csv._TRADE_DATES_CACHE_TTL_SECONDS + 10,
    )
    monkeypatch.delenv("ALLOW_APPROX_TRADE_CALENDAR", raising=False)
    monkeypatch.setattr(
        fetch_csv,
        "_fetch_trade_dates_from_sources",
        lambda cache_path: ([], RuntimeError("calendar down")),
    )

    assert fetch_csv._trade_dates() == [date(2026, 6, 13), date(2026, 6, 16)]


def test_get_all_stocks_uses_fresh_cache_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    stocks = [{"code": "688001", "name": "华兴源创"}]
    _write_json(tmp_path / "stock_list_cache.json", stocks)
    monkeypatch.setattr(fetch_csv, "_fetch_stocks_tushare", lambda: pytest.fail("unexpected tushare fetch"))
    monkeypatch.setattr(fetch_csv, "_fetch_stocks_akshare", lambda: pytest.fail("unexpected akshare fetch"))

    assert fetch_csv.get_all_stocks() == stocks


def test_get_all_stocks_returns_stale_cache_when_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    stocks = [{"code": "300750", "name": "宁德时代"}]
    _write_json(
        tmp_path / "stock_list_cache.json",
        stocks,
        age_seconds=fetch_csv._STOCK_LIST_CACHE_TTL_SECONDS + 10,
    )
    monkeypatch.setattr(fetch_csv, "_fetch_stocks_tushare", lambda: (_ for _ in ()).throw(RuntimeError("no ts")))
    monkeypatch.setattr(fetch_csv, "_fetch_stocks_akshare", lambda: (_ for _ in ()).throw(RuntimeError("no ak")))

    assert fetch_csv.get_all_stocks() == stocks


def test_get_all_stocks_writes_tushare_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use_tmp_cache(monkeypatch, tmp_path)
    stocks = [{"code": "000001", "name": "平安银行"}]
    monkeypatch.setattr(fetch_csv, "_fetch_stocks_tushare", lambda: stocks)
    monkeypatch.setattr(fetch_csv, "_fetch_stocks_akshare", lambda: pytest.fail("unexpected akshare fetch"))

    assert fetch_csv.get_all_stocks() == stocks
    cached = json.loads((tmp_path / "stock_list_cache.json").read_text(encoding="utf-8"))
    assert cached == stocks
