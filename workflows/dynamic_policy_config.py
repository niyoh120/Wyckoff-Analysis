"""Runtime configuration loader for dynamic AI candidate policy."""

from __future__ import annotations

import os

from core.dynamic_policy import DynamicPolicyConfig
from utils.env import env_int as _env_int


def dynamic_policy_config_from_env() -> DynamicPolicyConfig:
    return DynamicPolicyConfig(
        mode=os.getenv("FUNNEL_DYNAMIC_POLICY", "off").strip().lower(),
        horizon_days=_env_int("FUNNEL_DYNAMIC_POLICY_HORIZON", 5, minimum=1),
    )
