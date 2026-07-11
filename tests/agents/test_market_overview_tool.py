from __future__ import annotations

import pandas as pd
import pytest

from agents.market_tools import _normalize_trade_date, _tushare_market_breadth
from cli.tools import TOOL_SCHEMAS


def test_market_breadth_summarizes_cross_section() -> None:
    class Pro:
        def daily(self, **kwargs):
            assert kwargs == {"trade_date": "20260710"}
            return pd.DataFrame({"pct_chg": [2.0, 0.1, 0.0, -1.0, -6.0, None]})

    result = _tushare_market_breadth(Pro(), "20260710")

    assert result == {
        "trade_date": "20260710",
        "sample_size": 5,
        "up_count": 2,
        "down_count": 2,
        "flat_count": 1,
        "up_ratio_pct": 40.0,
        "median_pct_chg": 0.0,
        "average_pct_chg": -0.98,
        "up_5pct_count": 0,
        "down_5pct_count": 1,
    }


@pytest.mark.parametrize("value", ["2026-07-10", "20260710"])
def test_market_date_accepts_common_formats(value: str) -> None:
    assert _normalize_trade_date(value) == "20260710"


def test_market_date_rejects_ambiguous_input() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _normalize_trade_date("7月10日")


def test_market_overview_schema_exposes_historical_breadth() -> None:
    schema = next(item for item in TOOL_SCHEMAS if item["name"] == "get_market_overview")

    assert set(schema["parameters"]["properties"]) == {"trade_date", "include_breadth"}
