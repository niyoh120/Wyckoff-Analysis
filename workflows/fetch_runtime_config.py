"""Runtime config loader for OHLCV batch fetching."""

from __future__ import annotations

import os

from tools.ohlcv_fallback_fetcher import FetchRuntimeConfig


def fetch_runtime_config_from_env() -> FetchRuntimeConfig:
    return FetchRuntimeConfig(
        max_retries=_int_env("FUNNEL_FETCH_RETRIES", 2, min_value=1),
        retry_base_delay=_float_env("FUNNEL_RETRY_BASE_DELAY", 1.0, min_value=0.0),
        socket_timeout=_int_env("FUNNEL_SOCKET_TIMEOUT", 20, min_value=1),
        fetch_timeout=_int_env("FUNNEL_FETCH_TIMEOUT", 45, min_value=0),
        batch_timeout=_int_env("FUNNEL_BATCH_TIMEOUT", 420, min_value=1),
        batch_size=_int_env("FUNNEL_BATCH_SIZE", 200, min_value=1),
        batch_sleep=_float_env("FUNNEL_BATCH_SLEEP", 0.55, min_value=0.0),
        max_workers=_int_env("FUNNEL_MAX_WORKERS", 8, min_value=1),
        executor_mode=_executor_mode(os.getenv("FUNNEL_EXECUTOR_MODE", "process")),
    )


def _executor_mode(raw: str | None) -> str:
    mode = str(raw or "process").strip().lower()
    return mode if mode in {"thread", "process"} else "process"


def _int_env(name: str, default: int, *, min_value: int) -> int:
    try:
        value = int(float(os.getenv(name, str(default))))
    except ValueError:
        value = default
    return max(value, min_value)


def _float_env(name: str, default: float, *, min_value: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(value, min_value)
