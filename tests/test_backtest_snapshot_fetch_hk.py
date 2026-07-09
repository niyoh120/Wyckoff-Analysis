from __future__ import annotations

import json
from datetime import date

import pandas as pd

from workflows.backtest_snapshot_fetch_hk import _save_snapshot


def test_save_hk_snapshot_outputs_required_artifacts(tmp_path) -> None:
    full_df = pd.DataFrame({"date": ["2026-01-02"], "symbol": ["00700.HK"], "close": [350.0]})
    bench_df = pd.DataFrame({"date": ["2026-01-02"], "close": [18000.0]})

    status = _save_snapshot(
        tmp_path,
        full_df,
        bench_df,
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
    assert meta["benchmark"]


def test_save_hk_snapshot_fails_without_benchmark(tmp_path) -> None:
    full_df = pd.DataFrame({"date": ["2026-01-02"], "symbol": ["00700.HK"], "close": [350.0]})

    status = _save_snapshot(
        tmp_path,
        full_df,
        None,
        ["00700.HK"],
        1,
        {"00700.HK": "Tencent"},
        date(2025, 1, 1),
        date(2026, 1, 2),
    )

    assert status == 1
