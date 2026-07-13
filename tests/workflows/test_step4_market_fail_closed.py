from workflows.step4_market import normalize_premarket_regime, resolve_effective_market_regime


def test_invalid_premarket_regime_fails_closed() -> None:
    assert normalize_premarket_regime("typo") == "UNKNOWN"
    assert resolve_effective_market_regime("NEUTRAL", "typo") == "RISK_OFF"


def test_missing_premarket_regime_fails_closed() -> None:
    assert normalize_premarket_regime(None) == "UNKNOWN"
    assert resolve_effective_market_regime("NEUTRAL", None) == "RISK_OFF"


def test_repair_stages_survive_normal_premarket_merge() -> None:
    assert resolve_effective_market_regime("PANIC_REPAIR", "NORMAL") == "PANIC_REPAIR"
    assert resolve_effective_market_regime("PANIC_REPAIR_CONFIRMED", "NORMAL") == "PANIC_REPAIR_CONFIRMED"
    assert resolve_effective_market_regime("PANIC_REPAIR_CONFIRMED", "CAUTION") == "PANIC_REPAIR_CONFIRMED"
    assert resolve_effective_market_regime("PANIC_REPAIR_CONFIRMED", "RISK_OFF") == "RISK_OFF"
