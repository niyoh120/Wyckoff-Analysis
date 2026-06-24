"""Runtime LLM configuration for Step3 compliance reports."""

from __future__ import annotations

import os

from core.compliance_report import DEFAULT_MAX_OUTPUT_TOKENS, EFFICIENCY_PROVIDER, ComplianceLLMConfig

_TRUE_TEXTS = {"1", "true", "yes", "on"}


def compliance_llm_config_from_env() -> ComplianceLLMConfig | None:
    if not _env_bool("STEP3_COMPLIANCE_LLM_ENABLED", True):
        return None
    api_key = os.getenv("EFFICIENCY_API_KEY", "").strip()
    model = os.getenv("EFFICIENCY_MODEL", "").strip()
    base_url = os.getenv("EFFICIENCY_BASE_URL", "").strip()
    if not (api_key and model and base_url):
        return None
    return ComplianceLLMConfig(
        provider=EFFICIENCY_PROVIDER,
        api_key=api_key,
        model=model,
        base_url=base_url,
        source="efficiency",
        retries=max(_env_int("STEP3_COMPLIANCE_MAX_RETRIES", 1), 0),
        max_output_tokens=max(_env_int("STEP3_COMPLIANCE_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS), 512),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in _TRUE_TEXTS


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except Exception:
        return default
