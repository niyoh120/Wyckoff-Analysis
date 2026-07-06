"""Dynamic AI candidate allocation driven by signal health."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from core.ai_candidate_allocation import fit_ai_candidate_quotas
from core.signal_feedback import BLOCKED_REGISTRY_STATUSES, normalize_signal_type, signal_track
from utils.safe import safe_float


@dataclass(frozen=True)
class DynamicPolicyConfig:
    mode: str = "off"
    horizon_days: int = 5

    def normalized_mode(self) -> str:
        mode = str(self.mode or "off").strip().lower()
        return mode if mode in {"off", "shadow", "on"} else "off"

    def normalized_horizon(self) -> int:
        try:
            return max(int(self.horizon_days), 1)
        except (TypeError, ValueError):
            return 5


DEFAULT_DYNAMIC_POLICY_CONFIG = DynamicPolicyConfig()


def dynamic_policy_mode(config: DynamicPolicyConfig | None = None) -> str:
    mode = (config or DEFAULT_DYNAMIC_POLICY_CONFIG).normalized_mode()
    return mode if mode in {"off", "shadow", "on"} else "off"


def dynamic_policy_horizon(config: DynamicPolicyConfig | None = None) -> int:
    return (config or DEFAULT_DYNAMIC_POLICY_CONFIG).normalized_horizon()


def _registry_status_map(registry_rows: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in registry_rows or []:
        signal_type = normalize_signal_type(row.get("signal_type"))
        if signal_type:
            out[signal_type] = str(row.get("status") or "ACTIVE").strip().upper()
    return out


def filter_triggers_by_registry(
    triggers: dict[str, list[tuple[str, float]]],
    registry_rows: list[dict[str, Any]],
) -> dict[str, list[tuple[str, float]]]:
    statuses = _registry_status_map(registry_rows)
    if not statuses:
        return triggers
    filtered: dict[str, list[tuple[str, float]]] = {}
    for signal_type, hits in (triggers or {}).items():
        sig = normalize_signal_type(signal_type)
        if statuses.get(sig, "ACTIVE") in BLOCKED_REGISTRY_STATUSES:
            continue
        filtered[signal_type] = hits
    return filtered


def _latest_health_by_signal(
    health_rows: list[dict[str, Any]],
    regime: str,
    horizon_days: int,
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    regime_norm = str(regime or "NEUTRAL").strip().upper() or "NEUTRAL"
    for row in sorted(health_rows or [], key=lambda r: str(r.get("as_of_date") or ""), reverse=True):
        if int(row.get("horizon_days") or 0) != horizon_days:
            continue
        row_regime = str(row.get("regime") or "ALL").strip().upper()
        if row_regime not in {regime_norm, "ALL"}:
            continue
        signal_type = normalize_signal_type(row.get("signal_type"))
        if signal_type and (signal_type not in selected or row_regime == regime_norm):
            selected[signal_type] = row
    return selected


def build_signal_weight_map(
    health_rows: list[dict[str, Any]],
    registry_rows: list[dict[str, Any]] | None = None,
    *,
    regime: str = "NEUTRAL",
    horizon_days: int | None = None,
    config: DynamicPolicyConfig | None = None,
) -> dict[str, float]:
    weights: dict[str, float] = {}
    horizon = dynamic_policy_horizon(config) if horizon_days is None else max(int(horizon_days), 1)
    for signal_type, row in _latest_health_by_signal(health_rows, regime, horizon).items():
        weights[signal_type] = max(safe_float(row.get("weight_multiplier")), 0.0)
    for row in registry_rows or []:
        signal_type = normalize_signal_type(row.get("signal_type"))
        if not signal_type:
            continue
        status = str(row.get("status") or "ACTIVE").strip().upper()
        reg_weight = max(safe_float(row.get("weight_multiplier")), 0.0)
        weights[signal_type] = (
            0.0 if status in BLOCKED_REGISTRY_STATUSES else min(weights.get(signal_type, 1.0), reg_weight)
        )
    return weights


def merge_signal_weight_maps(*maps: dict[str, float] | None) -> dict[str, float]:
    merged: dict[str, float] = {}
    signals = sorted({signal for item in maps if item for signal in item})
    for signal in signals:
        weights = [safe_float(item.get(signal)) for item in maps if item and signal in item]
        downweights = [weight for weight in weights if weight < 1.0]
        merged[signal] = min(downweights) if downweights else max(weights)
    return merged


def _track_weights(signal_weights: dict[str, float]) -> tuple[float, float]:
    trend = [w for sig, w in signal_weights.items() if signal_track(_base_signal_key(sig)) == "Trend"]
    accum = [w for sig, w in signal_weights.items() if signal_track(_base_signal_key(sig)) == "Accum"]
    return (float(mean(trend)) if trend else 1.0, float(mean(accum)) if accum else 1.0)


def _base_signal_key(raw: Any) -> str:
    return str(raw or "").split("|", 1)[0].strip()


def _apply_breadth_bias(trend_weight: float, accum_weight: float, breadth: dict | None) -> tuple[float, float]:
    delta = breadth.get("delta_pct") if breadth else None
    if delta is None:
        return trend_weight, accum_weight
    delta_f = safe_float(delta, default=0.0)
    if delta_f >= 5.0:
        return trend_weight * 1.1, accum_weight * 0.95
    if delta_f <= -5.0:
        return trend_weight * 0.85, accum_weight * 1.05
    return trend_weight, accum_weight


def resolve_dynamic_candidate_policy(
    base_policy: dict[str, Any],
    signal_weights: dict[str, float],
    *,
    breadth: dict | None = None,
) -> dict[str, Any]:
    trend_weight, accum_weight = _apply_breadth_bias(*_track_weights(signal_weights), breadth)
    requested_trend = int(base_policy.get("requested_trend_quota") or base_policy.get("trend_quota") or 0)
    requested_accum = int(base_policy.get("requested_accum_quota") or base_policy.get("accum_quota") or 0)
    requested_total = max(requested_trend + requested_accum, 0)
    if requested_total <= 0:
        return dict(base_policy)
    trend_raw = max(requested_trend * trend_weight, 0.0)
    accum_raw = max(requested_accum * accum_weight, 0.0)
    if trend_raw + accum_raw <= 0:
        return dict(base_policy)
    dynamic_trend = int(round(requested_total * trend_raw / (trend_raw + accum_raw)))
    dynamic_accum = max(requested_total - dynamic_trend, 0)
    trend_quota, accum_quota = fit_ai_candidate_quotas(
        int(base_policy.get("total_cap") or 0), dynamic_trend, dynamic_accum
    )
    out = dict(base_policy)
    out.update(
        {
            "quota_family": f"{base_policy.get('quota_family', 'NEUTRAL')}+DYNAMIC",
            "requested_trend_quota": dynamic_trend,
            "requested_accum_quota": dynamic_accum,
            "trend_quota": trend_quota,
            "accum_quota": accum_quota,
            "trend_health_weight": round(trend_weight, 3),
            "accum_health_weight": round(accum_weight, 3),
        }
    )
    return out
