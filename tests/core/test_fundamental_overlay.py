from core.fundamental_overlay import evaluate_fundamental_overlay


def test_strong_fundamentals_boost_confidence() -> None:
    result = evaluate_fundamental_overlay(
        {
            "period_end": "2024-12-31",
            "roe": 18,
            "net_income_yoy": 20,
            "revenue_yoy": 12,
            "gross_margin": 35,
            "debt_to_asset_ratio": 40,
            "operating_cash_to_revenue": 8,
        },
        signal_date="2025-04-30",
    )

    assert result["grade"] == "strong"
    assert result["action"] == "boost"
    assert result["confidence_delta"] == 1


def test_distressed_fundamentals_are_veto_only_overlay() -> None:
    result = evaluate_fundamental_overlay(
        {
            "period_end": "2024-12-31",
            "roe": -5,
            "net_income_yoy": -45,
            "revenue_yoy": -25,
            "debt_to_asset_ratio": 88,
            "operating_cash_to_revenue": -3,
        },
        signal_date="2025-04-30",
    )

    assert result["grade"] == "weak"
    assert result["action"] == "veto"
    assert result["position_cap"] == 0


def test_stale_or_thin_record_stays_unknown() -> None:
    result = evaluate_fundamental_overlay(
        {"period_end": "2020-12-31", "roe": 20, "revenue_yoy": 10},
        signal_date="2025-04-30",
    )

    assert result["grade"] == "unknown"
    assert result["action"] == "observe"


def test_profit_without_cash_conversion_flags_divergence() -> None:
    result = evaluate_fundamental_overlay(
        {
            "period_end": "2024-12-31",
            "roe": 12,
            "net_income_yoy": 8,
            "revenue_yoy": 5,
            "gross_margin": 40,
            "debt_to_asset_ratio": 40,
            "operating_cash_to_revenue": -5,
        },
        signal_date="2025-04-30",
    )

    assert "PROFIT_CASH_FLOW_DIVERGENCE" in result["negative_rules"]
    assert "WEAK_CASH_EARNINGS" in result["negative_rules"]
