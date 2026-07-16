from core.market_trade_mode import EXECUTE_BLOCK_NEW_BUY_REGIMES, KNOWN_MARKET_REGIMES, MARKET_EXECUTION_PRIORITY
from workflows.step4_market import (
    normalize_premarket_regime,
    resolve_effective_market_regime,
)


def test_invalid_premarket_regime_fails_closed() -> None:
    assert normalize_premarket_regime("typo") == "UNKNOWN"
    assert resolve_effective_market_regime("NEUTRAL", "typo") == "UNKNOWN"


def test_missing_premarket_regime_fails_closed() -> None:
    assert normalize_premarket_regime(None) == "UNKNOWN"
    assert resolve_effective_market_regime("NEUTRAL", None) == "UNKNOWN"


def test_repair_stages_survive_normal_premarket_merge() -> None:
    assert resolve_effective_market_regime("PANIC_REPAIR", "NORMAL") == "PANIC_REPAIR"
    assert resolve_effective_market_regime("PANIC_REPAIR_CONFIRMED", "NORMAL") == "PANIC_REPAIR_CONFIRMED"
    assert resolve_effective_market_regime("PANIC_REPAIR_CONFIRMED", "CAUTION") == "PANIC_REPAIR_CONFIRMED"
    assert resolve_effective_market_regime("PANIC_REPAIR_CONFIRMED", "RISK_OFF") == "RISK_OFF"


def test_caution_and_risk_on_keep_their_execution_semantics() -> None:
    assert resolve_effective_market_regime("CAUTION", "NORMAL") == "CAUTION"
    assert resolve_effective_market_regime("RISK_ON", "NORMAL") == "RISK_ON"
    assert resolve_effective_market_regime("RISK_ON", "CAUTION") == "RISK_ON"


def test_every_emitted_benchmark_regime_has_explicit_execution_priority() -> None:
    assert KNOWN_MARKET_REGIMES <= MARKET_EXECUTION_PRIORITY.keys()


def test_no_source_level_hard_block_can_escape_after_merge() -> None:
    benchmark_regimes = KNOWN_MARKET_REGIMES | {"UNKNOWN"}
    premarket_regimes = {"UNKNOWN", "NORMAL", "CAUTION", "RISK_OFF", "BLACK_SWAN"}
    for benchmark in benchmark_regimes:
        for premarket in premarket_regimes:
            effective = resolve_effective_market_regime(benchmark, premarket)
            if benchmark in EXECUTE_BLOCK_NEW_BUY_REGIMES or premarket in EXECUTE_BLOCK_NEW_BUY_REGIMES:
                assert effective in EXECUTE_BLOCK_NEW_BUY_REGIMES, f"{benchmark}+{premarket} escaped as {effective}"


def test_worsening_premarket_never_increases_execution_permission() -> None:
    def permission(regime: str) -> int:
        if regime in EXECUTE_BLOCK_NEW_BUY_REGIMES:
            return 0
        if regime in {"CAUTION", "CRASH_LEFT_PROBE", "PANIC_REPAIR_CONFIRMED", "PANIC_REPAIR_INTRADAY"}:
            return 1
        return 2

    for benchmark in KNOWN_MARKET_REGIMES | {"UNKNOWN"}:
        permissions = [
            permission(resolve_effective_market_regime(benchmark, premarket))
            for premarket in ("NORMAL", "CAUTION", "RISK_OFF", "BLACK_SWAN")
        ]
        assert permissions == sorted(permissions, reverse=True), f"{benchmark}: {permissions}"
