"""Runtime config loader for market liquidity metrics."""

from __future__ import annotations

import os

from tools.market_liquidity import AmountDistributionConfig, MoneyFlowConfig


def market_money_flow_config_from_env() -> MoneyFlowConfig:
    return MoneyFlowConfig(
        lookback=_int_env("FUNNEL_MONEY_FLOW_LOOKBACK", 20, min_value=2),
        expand_ratio=_float_env("FUNNEL_MONEY_FLOW_EXPAND_RATIO", 1.10),
        contract_ratio=_float_env("FUNNEL_MONEY_FLOW_CONTRACT_RATIO", 0.85),
        dominance_ratio=max(_float_env("FUNNEL_MONEY_FLOW_DOMINANCE_RATIO", 1.20), 0.01),
    )


def amount_distribution_config_from_env() -> AmountDistributionConfig:
    return AmountDistributionConfig(
        lookback=_int_env("FUNNEL_AMOUNT_DISTRIBUTION_LOOKBACK", 20, min_value=2),
        skew_threshold=_float_env("FUNNEL_AMOUNT_DISTRIBUTION_SKEW_THRESHOLD", 2.5),
        thin_pass_ratio=_bounded_float_env("FUNNEL_AMOUNT_DISTRIBUTION_THIN_PASS_RATIO", 0.35, 0.0, 1.0),
    )


def _int_env(name: str, default: int, *, min_value: int) -> int:
    try:
        return max(int(float(os.getenv(name, str(default)))), min_value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bounded_float_env(name: str, default: float, lower: float, upper: float) -> float:
    return min(max(_float_env(name, default), lower), upper)
