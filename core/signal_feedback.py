"""Signal observation, outcome, and health aggregation helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean, median
from typing import Any

SIGNAL_TRACK: dict[str, str] = {
    "sos": "Trend",
    "evr": "Trend",
    "trend_pullback": "Trend",
    "spring": "Accum",
    "lps": "Accum",
    "compression": "Accum",
}
KNOWN_SIGNALS = set(SIGNAL_TRACK)
BLOCKED_REGISTRY_STATUSES = {"EXPERIMENTAL", "RETIRED"}


def normalize_signal_type(raw: Any) -> str:
    return str(raw or "").strip().lower()


def signal_track(signal_type: Any) -> str:
    return SIGNAL_TRACK.get(normalize_signal_type(signal_type), "Trend")


def _code(raw: Any) -> str:
    return str(raw or "").strip()


def _float(raw: Any, default: float = 0.0) -> float:
    try:
        if raw is None or str(raw).strip() == "":
            return default
        return float(raw)
    except (TypeError, ValueError):
        return default


def _iter_trigger_rows(triggers: dict[str, list[tuple[str, float]]]):
    for signal_type, hits in (triggers or {}).items():
        sig = normalize_signal_type(signal_type)
        for code, score in hits or []:
            code_s = _code(code)
            if code_s and sig:
                yield sig, code_s, _float(score)


def _springboard_observation_fields(
    signal_type: str,
    code: str,
    springboard_map: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    fields = (springboard_map or {}).get(f"{signal_type}:{code}") or (springboard_map or {}).get(code)
    if not fields:
        return {}
    return {
        "springboard_grade": fields.get("springboard_grade"),
        "springboard_met_count": fields.get("springboard_met_count"),
        "springboard_a": fields.get("springboard_a"),
        "springboard_b": fields.get("springboard_b"),
        "springboard_c": fields.get("springboard_c"),
        "springboard_support": fields.get("springboard_support"),
        "springboard_touch_count": fields.get("springboard_touch_count"),
        "springboard_evidence": fields.get("springboard_evidence") or {},
    }


def build_signal_observations(
    trade_date: str,
    triggers: dict[str, list[tuple[str, float]]],
    *,
    market: str = "cn",
    regime: str = "NEUTRAL",
    selected_for_ai: list[str] | None = None,
    ai_recommended: list[str] | None = None,
    name_map: dict[str, str] | None = None,
    sector_map: dict[str, str] | None = None,
    score_map: dict[str, float] | None = None,
    stage_map: dict[str, str] | None = None,
    channel_map: dict[str, str] | None = None,
    latest_close_map: dict[str, float] | None = None,
    source_map: dict[str, str] | None = None,
    springboard_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    selected = {_code(c) for c in selected_for_ai or []}
    recommended = {_code(c) for c in ai_recommended or []}
    now_iso = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []
    for signal_type, code, trigger_score in _iter_trigger_rows(triggers):
        rows.append(
            {
                "market": market,
                "trade_date": trade_date,
                "code": code,
                "name": (name_map or {}).get(code, code),
                "signal_type": signal_type,
                "track": signal_track(signal_type),
                "regime": str(regime or "NEUTRAL").strip().upper() or "NEUTRAL",
                "industry": (sector_map or {}).get(code, ""),
                "stage": (stage_map or {}).get(code, ""),
                "channel": (channel_map or {}).get(code, ""),
                "trigger_score": trigger_score,
                "priority_score": _float((score_map or {}).get(code)),
                "entry_price": _float((latest_close_map or {}).get(code), default=0.0),
                "selected_for_ai": code in selected,
                "ai_recommended": code in recommended,
                "source": (source_map or {}).get(code, "funnel"),
                "lifecycle_status": "ACTIVE",
                "updated_at": now_iso,
                **_springboard_observation_fields(signal_type, code, springboard_map),
            }
        )
    return rows


def classify_health(
    sample_count: int,
    win_rate_pct: float | None,
    avg_return_pct: float | None,
    *,
    min_samples: int = 20,
) -> tuple[str, float, str]:
    if sample_count < min_samples:
        return "INSUFFICIENT", 0.8, f"samples {sample_count}<{min_samples}"
    win = float(win_rate_pct or 0.0)
    avg = float(avg_return_pct or 0.0)
    if win < 35.0 and avg < 0.0:
        return "DECAYED", 0.4, f"win={win:.1f}%, avg={avg:+.2f}%"
    if win < 40.0 or avg < 0.0:
        return "WATCH", 0.75, f"win={win:.1f}%, avg={avg:+.2f}%"
    return "HEALTHY", 1.0, f"win={win:.1f}%, avg={avg:+.2f}%"


def _done_return(row: dict[str, Any]) -> float | None:
    if str(row.get("status", "")).strip().lower() != "done":
        return None
    raw = row.get("return_pct")
    return None if raw is None else _float(raw)


def _health_row(
    as_of_date: str,
    market: str,
    key: tuple[str, str, str, int],
    rows: list[dict[str, Any]],
    min_samples: int,
) -> dict[str, Any]:
    signal_type, track, regime, horizon = key
    returns = [r for r in (_done_return(row) for row in rows) if r is not None]
    drawdowns = [_float(row.get("max_drawdown_pct")) for row in rows if row.get("max_drawdown_pct") is not None]
    win_rate = float(sum(1 for r in returns if r > 0) / len(returns) * 100.0) if returns else None
    avg_ret = float(mean(returns)) if returns else None
    state, weight, reason = classify_health(len(returns), win_rate, avg_ret, min_samples=min_samples)
    return {
        "market": market,
        "as_of_date": as_of_date,
        "signal_type": signal_type,
        "track": track,
        "regime": regime,
        "horizon_days": horizon,
        "sample_count": len(returns),
        "win_rate_pct": win_rate,
        "avg_return_pct": avg_ret,
        "median_return_pct": float(median(returns)) if returns else None,
        "avg_drawdown_pct": float(mean(drawdowns)) if drawdowns else None,
        "health_state": state,
        "weight_multiplier": weight,
        "reason": reason,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _registry_status_by_signal(rows: list[dict[str, Any]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows or []:
        signal_type = normalize_signal_type(row.get("signal_type"))
        if signal_type:
            out[signal_type] = str(row.get("status") or "ACTIVE").strip().upper()
    return out


def _next_registry_status(signal_type: str, health_state: str, current_status: str) -> str:
    if health_state == "HEALTHY":
        return "ACTIVE"
    if health_state == "INSUFFICIENT":
        return "ACTIVE" if signal_type in KNOWN_SIGNALS else "EXPERIMENTAL"
    if current_status == "RETIRED":
        return "RETIRED"
    if health_state == "DECAYED" and current_status == "WATCH":
        return "RETIRED"
    return "WATCH"


def summarize_signal_health(
    outcomes: list[dict[str, Any]],
    *,
    as_of_date: str,
    market: str = "cn",
    min_samples: int = 20,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        signal_type = normalize_signal_type(row.get("signal_type"))
        if not signal_type:
            continue
        track = str(row.get("track") or signal_track(signal_type))
        regime = str(row.get("regime") or "NEUTRAL").strip().upper() or "NEUTRAL"
        horizon = int(row.get("horizon_days") or 0)
        if horizon <= 0:
            continue
        groups[(signal_type, track, regime, horizon)].append(row)
        groups[(signal_type, track, "ALL", horizon)].append(row)
    return [_health_row(as_of_date, market, key, rows, min_samples) for key, rows in sorted(groups.items())]


def build_signal_registry_updates(
    health_rows: list[dict[str, Any]],
    *,
    market: str = "cn",
    horizon_days: int = 10,
    registry_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = [r for r in health_rows if r.get("regime") == "ALL" and int(r.get("horizon_days") or 0) == horizon_days]
    status_by_signal = _registry_status_by_signal(registry_rows)
    updates = []
    for row in rows:
        state = str(row.get("health_state") or "INSUFFICIENT")
        signal_type = normalize_signal_type(row.get("signal_type"))
        current_status = status_by_signal.get(signal_type, "ACTIVE")
        status = _next_registry_status(signal_type, state, current_status)
        updates.append(
            {
                "market": market,
                "signal_type": signal_type,
                "track": row.get("track") or signal_track(signal_type),
                "status": status,
                "weight_multiplier": row.get("weight_multiplier") or 1.0,
                "sample_count": row.get("sample_count") or 0,
                "win_rate_pct": row.get("win_rate_pct"),
                "avg_return_pct": row.get("avg_return_pct"),
                "horizon_days": horizon_days,
                "reason": row.get("reason") or "",
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
    return updates
