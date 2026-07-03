"""Small environment parsing helpers for entrypoint and workflow layers."""

from __future__ import annotations

import os


def parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def parse_int_env(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except Exception:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return parse_bool(raw)


def env_flag(name: str) -> bool:
    return parse_bool(os.getenv(name, ""))


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    try:
        value = int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default
    return value if minimum is None else max(value, minimum)


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
