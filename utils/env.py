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
