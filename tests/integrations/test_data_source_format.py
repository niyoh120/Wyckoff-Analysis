from __future__ import annotations

from datetime import date

import pandas as pd

from integrations.data_source_format import (
    STOCK_HIST_COLUMNS,
    hist_date_text,
    normalize_efinance_columns,
    tickflow_adjust_mode,
    tickflow_daily_count,
    tickflow_daily_frame,
    tickflow_daily_window,
    to_ts_code,
)


def test_to_ts_code_resolves_cn_exchange_suffix() -> None:
    assert to_ts_code("600519") == "600519.SH"
    assert to_ts_code("000001") == "000001.SZ"
    assert to_ts_code("600519.SH") == "600519.SH"


def test_normalize_efinance_columns_returns_standard_stock_hist_columns() -> None:
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

    out = normalize_efinance_columns(raw)

    assert tuple(out.columns) == STOCK_HIST_COLUMNS
    assert out.iloc[0]["日期"] == "2026-06-01"
    assert pd.isna(out.iloc[0]["换手率"])


def test_tickflow_daily_frame_uses_standard_columns_and_adjust_modes() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-06-01", "2026-06-02"],
            "open": [10.0, 10.2],
            "high": [10.5, 10.8],
            "low": [9.8, 10.1],
            "close": [10.2, 10.6],
            "prev_close": [10.0, 10.2],
            "volume": [1000, 1200],
            "amount": [10200, 12720],
        }
    )

    out = tickflow_daily_frame(raw, date(2026, 6, 1), date(2026, 6, 2))

    assert tuple(out.columns) == STOCK_HIST_COLUMNS
    assert list(out["日期"]) == ["2026-06-01", "2026-06-02"]
    assert round(float(out.iloc[0]["涨跌幅"]), 2) == 2.0
    assert tickflow_adjust_mode("") == "none"
    assert tickflow_adjust_mode("qfq") == "forward"
    assert tickflow_adjust_mode("hfq") == "backward"


def test_tickflow_window_and_hist_date_text_normalize_dates() -> None:
    start_d, end_d, start_ms, end_ms = tickflow_daily_window("20260601", "20260602")

    assert start_d == date(2026, 6, 1)
    assert end_d == date(2026, 6, 2)
    assert start_ms < end_ms
    assert tickflow_daily_count(start_d, end_d, 10000) == 64
    assert hist_date_text(date(2026, 6, 2)) == "20260602"
    assert hist_date_text("2026-06-02") == "20260602"
