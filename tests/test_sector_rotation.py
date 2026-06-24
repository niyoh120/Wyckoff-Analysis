from __future__ import annotations

import pandas as pd

from core.sector_rotation import analyze_sector_rotation


def _healthy_member_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=60)
    close = pd.Series([10.0 + i * 0.1 for i in range(60)])
    volume = pd.Series([1_000_000.0] * 60)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        }
    )


def test_analyze_sector_rotation_marks_healthy_mainline() -> None:
    df_map = {code: _healthy_member_frame() for code in ("000001", "000002", "000003")}
    sector_map = {code: "银行" for code in df_map}

    result = analyze_sector_rotation(df_map, sector_map)

    info = result["state_map"]["银行"]
    assert info["state"] == "HEALTHY_MAINLINE"
    assert result["counts"]["HEALTHY_MAINLINE"] == 1
    assert info["above_ma50_pct"] == 100.0
    assert result["headline"] == "分歧0 | 健康1 | 高潮0 | 退潮0 | 中性0"
    assert result["overview_lines"]
