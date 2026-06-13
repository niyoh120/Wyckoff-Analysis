"""Public payload shaping for funnel results."""

from __future__ import annotations

from typing import Any

_HEAVY_FUNNEL_KEYS = {"all_df_map", "financial_map"}


def public_funnel_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    return {
        str(key): value
        for key, value in metrics.items()
        if str(key) not in _HEAVY_FUNNEL_KEYS and not str(key).startswith("_")
    }


def public_funnel_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    out = {str(key): value for key, value in details.items() if str(key) not in _HEAVY_FUNNEL_KEYS}
    out["metrics"] = public_funnel_metrics(out.get("metrics"))
    return out
