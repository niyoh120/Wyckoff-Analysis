from core.market_trade_mode import resolve_market_trade_mode


def test_trade_mode_blocks_new_buy_in_weak_market() -> None:
    mode = resolve_market_trade_mode("bear_rebound")

    assert mode.mode == "observe_only"
    assert mode.allow_ai_review is False
    assert mode.allow_recommendation_write is False
    assert mode.allow_bypass_review is False


def test_trade_mode_keeps_neutral_confirmation_only() -> None:
    mode = resolve_market_trade_mode("NEUTRAL")

    assert mode.mode == "confirmation_only"
    assert mode.allow_ai_review is True
    assert mode.allow_full_l4 is False
    assert mode.allow_bypass_review is False


def test_trade_mode_allows_risk_on_promotions() -> None:
    mode = resolve_market_trade_mode("RISK_ON")

    assert mode.mode == "risk_on"
    assert mode.allow_ai_review is True
    assert mode.allow_full_l4 is True
    assert mode.allow_theme_promotion is True
