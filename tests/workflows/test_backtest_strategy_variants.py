from workflows.backtest_strategy_variants import normalize_strategy_variant, strategy_variant_overrides


def test_strategy_variants_isolate_each_research_switch() -> None:
    baseline = strategy_variant_overrides("A")
    assert not any(baseline.values())
    assert strategy_variant_overrides("B")["dist_upthrust_enabled"] is True
    assert strategy_variant_overrides("C")["regime_trigger_profiles_enabled"] is True
    assert strategy_variant_overrides("D") == {
        "dist_upthrust_enabled": False,
        "regime_trigger_profiles_enabled": False,
        "lps_creek_confirmation_enabled": True,
        "signal_sequence_bonus_enabled": True,
    }
    assert all(strategy_variant_overrides("E").values())


def test_live_variant_preserves_production_configuration() -> None:
    assert normalize_strategy_variant("live") == "live"
    assert strategy_variant_overrides("live") == {}
