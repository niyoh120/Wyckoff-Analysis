from __future__ import annotations

from datetime import date

import pandas as pd

from scripts import single_symbol_funnel_diagnosis as diag


def _daily_frame(rows: int = 230) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = pd.Series(range(rows), dtype="float64") * 0.1 + 20.0
    volume = pd.Series([1_000_000 + index * 1000 for index in range(rows)], dtype="float64")
    df = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "date_obj": [item.date() for item in dates],
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volume,
            "amount": close * volume,
            "pct_chg": close.pct_change().fillna(0.0) * 100.0,
        }
    )
    return df


def test_detect_symbol_market_normalizes_cn_hk_us():
    assert diag.detect_symbol_market("603390") == diag.SymbolSpec("cn", "603390", "A股")
    assert diag.detect_symbol_market("700") == diag.SymbolSpec("hk", "00700.HK", "港股")
    assert diag.detect_symbol_market("AAPL") == diag.SymbolSpec("us", "AAPL.US", "美股")
    assert diag.detect_symbol_market("msft.us") == diag.SymbolSpec("us", "MSFT.US", "美股")


def test_evaluate_day_reports_selected_trigger(monkeypatch):
    symbol = diag.SymbolSpec("us", "AAPL.US", "美股")
    cfg = diag.config_for_symbol(symbol, 220)
    ctx = diag.ReplayContext({"AAPL.US": "Apple"}, {}, {}, None)

    monkeypatch.setattr(diag, "layer1_filter", lambda symbols, *_args, **_kwargs: symbols)
    monkeypatch.setattr(
        diag, "layer2_strength_detailed", lambda symbols, *_args, **_kwargs: (symbols, {"AAPL.US": "main"}, [])
    )
    monkeypatch.setattr(diag, "layer3_sector_resonance", lambda symbols, *_args, **_kwargs: (symbols, []))
    monkeypatch.setattr(diag, "layer4_triggers", lambda *_args, **_kwargs: {"sos": [("AAPL.US", 12.5)]})

    row = diag._evaluate_day(symbol, _daily_frame(), ctx, cfg, date(2025, 11, 18))

    assert row.status == "SELECTED"
    assert row.failed_layer == "-"
    assert row.triggers == "SOS"
    assert "触发" in row.reason


def test_evaluate_day_reports_l4_miss(monkeypatch):
    symbol = diag.SymbolSpec("us", "AAPL.US", "美股")
    cfg = diag.config_for_symbol(symbol, 220)
    ctx = diag.ReplayContext({"AAPL.US": "Apple"}, {}, {}, None)

    monkeypatch.setattr(diag, "layer1_filter", lambda symbols, *_args, **_kwargs: symbols)
    monkeypatch.setattr(diag, "layer2_strength_detailed", lambda symbols, *_args, **_kwargs: (symbols, {}, []))
    monkeypatch.setattr(diag, "layer3_sector_resonance", lambda symbols, *_args, **_kwargs: (symbols, []))
    monkeypatch.setattr(diag, "layer4_triggers", lambda *_args, **_kwargs: {})

    row = diag._evaluate_day(symbol, _daily_frame(), ctx, cfg, date(2025, 11, 18))

    assert row.status == "MISS"
    assert row.failed_layer == "L4"
    assert "未触发正式" in row.reason
