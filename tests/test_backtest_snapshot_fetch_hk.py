from __future__ import annotations

import json
from datetime import date

import pandas as pd

from workflows.backtest_snapshot_fetch_hk import _fetch_benchmark, _save_snapshot


def test_save_hk_snapshot_outputs_required_artifacts(tmp_path) -> None:
    full_df = pd.DataFrame({"date": ["2026-01-02"], "symbol": ["00700.HK"], "close": [350.0]})
    bench_df = pd.DataFrame({"date": ["2026-01-02"], "close": [18000.0]})

    status = _save_snapshot(
        tmp_path,
        full_df,
        bench_df,
        "HSI.HK",
        ["00700.HK"],
        1,
        {"00700.HK": "Tencent"},
        date(2025, 1, 1),
        date(2026, 1, 2),
    )

    assert status == 0
    assert (tmp_path / "hist_full.csv.gz").exists()
    assert (tmp_path / "benchmark_main.csv").exists()
    assert json.loads((tmp_path / "name_map.json").read_text(encoding="utf-8")) == {"00700.HK": "Tencent"}
    meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert meta["market"] == "hk"
    assert meta["benchmark"] == "HSI.HK"


def test_save_hk_snapshot_fails_without_benchmark(tmp_path) -> None:
    full_df = pd.DataFrame({"date": ["2026-01-02"], "symbol": ["00700.HK"], "close": [350.0]})

    status = _save_snapshot(
        tmp_path,
        full_df,
        None,
        "",
        ["00700.HK"],
        1,
        {"00700.HK": "Tencent"},
        date(2025, 1, 1),
        date(2026, 1, 2),
    )

    assert status == 1


class _FakeBenchmarkClient:
    """模拟第一个候选代码取不到数据、第二个候选生效的场景。"""

    def __init__(self, valid_symbol: str) -> None:
        self.valid_symbol = valid_symbol
        self.requested: list[str] = []

    def get_klines_batch(self, symbols, **_kwargs):
        symbol = symbols[0]
        self.requested.append(symbol)
        if symbol != self.valid_symbol:
            return {}
        return {symbol: pd.DataFrame({"date": pd.date_range("2026-01-01", periods=60), "close": range(60)})}


def test_fetch_benchmark_falls_back_to_next_candidate() -> None:
    client = _FakeBenchmarkClient(valid_symbol="HSI.HK")

    bench_df, bench_symbol = _fetch_benchmark(client, count=60, start_ms=0, end_ms=1)

    assert bench_symbol == "HSI.HK"
    assert bench_df is not None and not bench_df.empty
    assert client.requested[0] != "HSI.HK"
    assert "HSI.HK" in client.requested


def test_fetch_benchmark_returns_none_when_all_candidates_fail() -> None:
    client = _FakeBenchmarkClient(valid_symbol="NOT_IN_LIST")

    bench_df, bench_symbol = _fetch_benchmark(client, count=60, start_ms=0, end_ms=1)

    assert bench_df is None
    assert bench_symbol == ""
