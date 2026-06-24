"""Runtime LLM configuration for public premarket briefs."""

from __future__ import annotations

import os

from core.premarket_public_brief import PublicBriefLlmConfig
from integrations.llm_client import provider_fallbacks, provider_route_chain, resolve_provider_name

_DISABLED_TEXTS = {"0", "false", "no", "off"}


def public_brief_llm_config_from_env() -> PublicBriefLlmConfig:
    if os.getenv("PREMARKET_LLM_ENABLED", "1").strip().lower() in _DISABLED_TEXTS:
        return PublicBriefLlmConfig()
    provider = resolve_provider_name("PREMARKET_LLM_PROVIDER", "efficiency")
    fallbacks = provider_fallbacks("PREMARKET_LLM_FALLBACK_PROVIDERS")
    return PublicBriefLlmConfig(
        routes=tuple(provider_route_chain(provider, fallbacks)),
        timeout_seconds=_env_int("PREMARKET_LLM_TIMEOUT", 45),
    )


def _env_int(name: str, default: int) -> int:
    try:
        return max(int(float(os.getenv(name, str(default)))), 1)
    except Exception:
        return default
