"""Safe type coercion and dict-cleanup helpers duplicated across agents/tools/core/integrations."""

from __future__ import annotations

import math
from typing import Any


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    """Best-effort float conversion; returns `default` for non-numeric or NaN/inf input."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def has_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if has_value(value)}
