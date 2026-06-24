"""Runtime configuration loader for dynamic AI candidate policy."""

from __future__ import annotations

import os

from core.dynamic_policy import DynamicPolicyConfig


def dynamic_policy_config_from_env() -> DynamicPolicyConfig:
    return DynamicPolicyConfig(
        mode=os.getenv("FUNNEL_DYNAMIC_POLICY", "off").strip().lower(),
        horizon_days=_env_int("FUNNEL_DYNAMIC_POLICY_HORIZON", 5),
    )


def _env_int(name: str, default: int) -> int:
    try:
        return max(int(float(os.getenv(name, str(default)))), 1)
    except (TypeError, ValueError):
        return default
