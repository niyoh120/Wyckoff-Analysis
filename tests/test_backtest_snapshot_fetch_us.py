from __future__ import annotations

import json
from datetime import date

import pandas as pd

from workflows.backtest_snapshot_fetch_us import _save_snapshot


def test_save_us_snapshot_outputs_required_artifacts(tmp_path) -> None:
    full_df = pd.DataFrame({"date": ["2026-01-02"], "symbol": ["AAPL.US"], "close": [200.0]})
    bench_df = pd.DataFrame({"date": ["2026-01-02"], "close": [500.0]})

    status = _save_snapshot(
        tmp_path,
        full_df,
        bench_df,
        ["AAPL.US"],
        1,
        {"AAPL.US": "Apple"},
        date(2025, 1, 1),
        date(2026, 1, 2),
    )

    assert status == 0
    assert (tmp_path / "hist_full.csv.gz").exists()
    assert (tmp_path / "benchmark_main.csv").exists()
    assert json.loads((tmp_path / "name_map.json").read_text(encoding="utf-8")) == {"AAPL.US": "Apple"}
    assert json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))["benchmark"]
