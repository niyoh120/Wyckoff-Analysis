from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from scripts.backtest_runner import _entry_on_or_after, _price_at_or_before


def test_price_at_or_before_uses_last_minute_before_target() -> None:
    day = datetime(2026, 1, 5).date()
    tz = ZoneInfo("Asia/Shanghai")
    df = pd.DataFrame(
        {
            "datetime": [
                datetime(2026, 1, 5, 14, 54, tzinfo=tz),
                datetime(2026, 1, 5, 14, 55, tzinfo=tz),
                datetime(2026, 1, 5, 14, 56, tzinfo=tz),
            ],
            "close": [10.1, 10.2, 10.3],
        }
    )

    assert _price_at_or_before(df, day, "14:55") == 10.2


def test_tail_1455_fallback_close_uses_daily_close(monkeypatch) -> None:
    monkeypatch.setattr("scripts.backtest_runner._resolve_tickflow_entry_price", lambda *_args: None)
    day = datetime(2026, 1, 5).date()
    df = pd.DataFrame({"date": [day], "open": [10.0], "high": [10.8], "low": [9.8], "close": [10.5]})

    price, entry_date, source = _entry_on_or_after(
        df,
        "000001",
        day,
        mode="tail_1455",
        entry_time="14:55",
        fallback="close",
        intraday_cache={},
    )

    assert price == 10.5
    assert entry_date == day
    assert source == "daily_close_fallback"


def test_tail_1455_fallback_skip_marks_missing(monkeypatch) -> None:
    monkeypatch.setattr("scripts.backtest_runner._resolve_tickflow_entry_price", lambda *_args: None)
    day = datetime(2026, 1, 5).date()
    df = pd.DataFrame({"date": [day], "open": [10.0], "high": [10.8], "low": [9.8], "close": [10.5]})

    price, entry_date, source = _entry_on_or_after(
        df,
        "000001",
        day,
        mode="tail_1455",
        entry_time="14:55",
        fallback="skip",
        intraday_cache={},
    )

    assert price is None
    assert entry_date is None
    assert source == "tail_1455_missing_skip"
