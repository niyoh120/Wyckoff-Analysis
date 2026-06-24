from integrations.supabase_market_signal import _merge_latest_market_signal_rows


def test_merge_latest_market_signal_rows_uses_latest_available_source_blocks():
    merged = _merge_latest_market_signal_rows(
        [
            {
                "trade_date": "2026-06-20",
                "premarket_regime": "NORMAL",
                "banner_title": "自定义标题",
                "banner_message": "自定义正文",
                "banner_tone": "custom",
            },
            {
                "trade_date": "2026-06-19",
                "benchmark_regime": "RISK_OFF",
                "main_index_code": "000001.SH",
                "main_index_close": 3000.12,
                "main_index_ma50": 3050.0,
                "main_index_ma200": 2900.0,
            },
            {
                "trade_date": "2026-06-18",
                "a50_value_date": "2026-06-18",
                "a50_close": 13200.5,
                "a50_pct_chg": -0.8,
                "vix_value_date": "2026-06-18",
                "vix_close": 18.2,
                "vix_pct_chg": 3.1,
            },
        ]
    )

    assert merged is not None
    assert merged["trade_date"] == "2026-06-19"
    assert merged["benchmark_regime"] == "RISK_OFF"
    assert merged["premarket_regime"] == "NORMAL"
    assert merged["a50_close"] == 13200.5
    assert merged["vix_close"] == 18.2
    assert merged["banner_title"] == "自定义标题"
    assert merged["banner_message"] == "自定义正文"
    assert merged["banner_tone"] == "custom"
