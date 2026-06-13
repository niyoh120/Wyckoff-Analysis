"""Public payload shaping for funnel results."""

from __future__ import annotations

from typing import Any

_HEAVY_FUNNEL_KEYS = {"all_df_map", "financial_map"}
_PRIVATE_FUNNEL_KEYS = {
    "external_seed_source",
    "external_seed_l1_codes",
    "external_seed_l2_codes",
    "external_seed_rejected_l1_codes",
    "external_seed_l4_triggers",
    "external_seed_l4_confirmed_codes",
    "external_seed_watch_codes",
    "external_seed_promoted_pool",
    "external_seed_observation_rows",
    "external_seed_triggers",
    "external_seed_selected",
}
_NON_PUBLIC_FUNNEL_KEYS = _HEAVY_FUNNEL_KEYS | _PRIVATE_FUNNEL_KEYS


def public_funnel_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    return {
        str(key): value
        for key, value in metrics.items()
        if str(key) not in _NON_PUBLIC_FUNNEL_KEYS and not str(key).startswith("_")
    }


def public_funnel_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    out = {str(key): value for key, value in details.items() if str(key) not in _NON_PUBLIC_FUNNEL_KEYS}
    out["metrics"] = public_funnel_metrics(out.get("metrics"))
    return out
