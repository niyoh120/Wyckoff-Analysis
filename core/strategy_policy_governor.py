"""Policy governance rules for attribution and shadow results."""

from __future__ import annotations

import json
import math
from typing import Any

VERSION = "strategy_policy_governor_v2"
MIN_SIGNAL_SAMPLES = 10
MIN_CONTEXT_SAMPLES = 5
MIN_SHADOW_RUNS = 10
MIN_SHADOW_MATCHED = 3
EXCLUDED_SIGNAL_TARGETS = {"unknown", "shadow_added", "shadow_removed"}


def build_strategy_policy_governor(
    *,
    signal_stats_json: dict[str, Any],
    signal_context_stats_json: dict[str, Any] | None = None,
    shadow_diff_stats_json: dict[str, Any],
    horizons: list[int],
) -> dict[str, Any]:
    horizon = _focus_horizon(horizons)
    shadow_gate = _shadow_gate(shadow_diff_stats_json, horizon)
    signal_actions = _signal_actions(signal_stats_json)
    context_actions = _context_actions(signal_context_stats_json or {})
    return {
        "version": VERSION,
        "horizon": str(horizon),
        "status": _governor_status(shadow_gate, signal_actions + context_actions),
        "auto_apply": False,
        "mode_recommendation": _mode_recommendation(shadow_gate),
        "shadow_gate": shadow_gate,
        "signal_actions": signal_actions,
        "context_actions": context_actions,
        "summary": _summary(shadow_gate, signal_actions),
    }


def governor_recommendation_rows(governor: dict[str, Any]) -> list[dict[str, str]]:
    rows = [_governor_summary_row(governor)]
    for action in (governor.get("signal_actions") or []) + (governor.get("context_actions") or []):
        if not isinstance(action, dict) or action.get("action") == "hold":
            continue
        rows.append(
            {
                "type": str(action.get("action") or "watch"),
                "horizon": str(action.get("horizon") or governor.get("horizon") or ""),
                "target": str(action.get("target") or ""),
                "reason": json.dumps(action, ensure_ascii=False),
            }
        )
    return rows


def signal_weight_multipliers_from_rows(
    rows: Any,
    *,
    horizon: str | int = "5",
) -> dict[str, float]:
    """Extract actionable signal weights from strategy attribution recommendations."""
    horizon_text = str(horizon)
    weights: dict[str, float] = {}
    for row in _json_rows(rows):
        action = _action_from_recommendation_row(row)
        if not action or str(action.get("horizon") or "") != horizon_text:
            continue
        target = str(action.get("target") or "").strip().lower()
        if not target or target in EXCLUDED_SIGNAL_TARGETS:
            continue
        multiplier = _bounded_multiplier(action.get("weight_multiplier"), str(action.get("action") or ""))
        if multiplier != 1.0:
            weights[_action_weight_key(action)] = multiplier
    return dict(sorted(weights.items()))


def scoped_signal_weight_key(
    signal_type: Any,
    *,
    regime: Any = "",
    lane: Any = "",
    entry_type: Any = "",
) -> str:
    signal = _norm_key(signal_type)
    parts = [signal]
    regime_text = str(regime or "").strip().upper()
    lane_text = _norm_key(lane)
    entry_text = _norm_key(entry_type)
    if regime_text and regime_text != "ALL":
        parts.append(f"regime={regime_text}")
    if lane_text and lane_text != "unknown":
        parts.append(f"lane={lane_text}")
    if entry_text and entry_text != "unknown":
        parts.append(f"entry={entry_text}")
    return "|".join(parts)


def signal_weight_lookup_keys(
    signal_type: Any,
    *,
    regime: Any = "",
    lane: Any = "",
    entry_type: Any = "",
) -> list[str]:
    signal = _norm_key(signal_type)
    regime_text = str(regime or "").strip().upper()
    lane_text = _norm_key(lane)
    entry_text = _norm_key(entry_type)
    keys = [
        scoped_signal_weight_key(signal, regime=regime_text, lane=lane_text, entry_type=entry_text),
        scoped_signal_weight_key(signal, regime=regime_text, lane=lane_text),
        scoped_signal_weight_key(signal, regime=regime_text, entry_type=entry_text),
        scoped_signal_weight_key(signal, lane=lane_text, entry_type=entry_text),
        scoped_signal_weight_key(signal, regime=regime_text),
        scoped_signal_weight_key(signal, lane=lane_text),
        scoped_signal_weight_key(signal, entry_type=entry_text),
        signal,
    ]
    return _dedup(keys)


def resolve_signal_weight_multiplier(
    weights: dict[str, float] | None,
    signal_type: Any,
    *,
    regime: Any = "",
    lane: Any = "",
    entry_type: Any = "",
) -> float:
    if not weights:
        return 1.0
    for key in signal_weight_lookup_keys(signal_type, regime=regime, lane=lane, entry_type=entry_type):
        value = _bounded_runtime_weight(weights.get(key))
        if value != 1.0:
            return value
    return 1.0


def _focus_horizon(horizons: list[int]) -> int:
    if 5 in horizons:
        return 5
    return int(horizons[0]) if horizons else 5


def _governor_summary_row(governor: dict[str, Any]) -> dict[str, str]:
    return {
        "type": "policy_governor",
        "horizon": str(governor.get("horizon") or ""),
        "target": "dynamic_policy",
        "reason": json.dumps(
            {
                "status": governor.get("status"),
                "mode_recommendation": governor.get("mode_recommendation"),
                "summary": governor.get("summary"),
                "auto_apply": governor.get("auto_apply"),
            },
            ensure_ascii=False,
        ),
    }


def _shadow_gate(shadow: dict[str, Any], horizon: int) -> dict[str, Any]:
    outcome_stats = shadow.get("outcome_stats") if isinstance(shadow, dict) else {}
    row = outcome_stats.get(str(horizon), {}) if isinstance(outcome_stats, dict) else {}
    added = row.get("added") if isinstance(row, dict) else {}
    removed = row.get("removed") if isinstance(row, dict) else {}
    evidence = _shadow_evidence(shadow, added or {}, removed or {})
    if (
        evidence["run_count"] < MIN_SHADOW_RUNS
        or evidence["added_matched"] < MIN_SHADOW_MATCHED
        or evidence["removed_matched"] < MIN_SHADOW_MATCHED
    ):
        status = "insufficient_sample"
    elif _shadow_added_outperforms(evidence):
        status = "candidate"
    elif _shadow_added_underperforms(evidence):
        status = "reject"
    else:
        status = "watch"
    return {"status": status, "horizon": str(horizon), **evidence}


def _shadow_evidence(shadow: dict[str, Any], added: dict[str, Any], removed: dict[str, Any]) -> dict[str, Any]:
    added_return = _num(added.get("avg_return_pct"))
    removed_return = _num(removed.get("avg_return_pct"))
    added_win = _num(added.get("win_rate_pct"))
    removed_win = _num(removed.get("win_rate_pct"))
    added_dd = _num(added.get("avg_drawdown_pct"))
    removed_dd = _num(removed.get("avg_drawdown_pct"))
    return {
        "run_count": int(shadow.get("count") or 0),
        "avg_added": _round(shadow.get("avg_added")),
        "avg_removed": _round(shadow.get("avg_removed")),
        "added_matched": int(added.get("matched_outcomes") or added.get("count") or 0),
        "removed_matched": int(removed.get("matched_outcomes") or removed.get("count") or 0),
        "added_avg_return_pct": _round(added_return),
        "removed_avg_return_pct": _round(removed_return),
        "return_lift_pct": _round((added_return or 0.0) - (removed_return or 0.0)),
        "win_rate_lift_pct": _round((added_win or 0.0) - (removed_win or 0.0)),
        "drawdown_lift_pct": _round((added_dd or 0.0) - (removed_dd or 0.0)),
    }


def _shadow_added_outperforms(evidence: dict[str, Any]) -> bool:
    return (
        _num(evidence.get("return_lift_pct"), 0.0) >= 2.0
        and _num(evidence.get("win_rate_lift_pct"), 0.0) >= 10.0
        and _num(evidence.get("drawdown_lift_pct"), 0.0) >= -3.0
    )


def _shadow_added_underperforms(evidence: dict[str, Any]) -> bool:
    return _num(evidence.get("return_lift_pct"), 0.0) <= -2.0 or _num(evidence.get("win_rate_lift_pct"), 0.0) <= -10.0


def _signal_actions(signal_stats_json: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for horizon, stats_by_signal in sorted((signal_stats_json or {}).items(), key=lambda item: int(item[0])):
        if not isinstance(stats_by_signal, dict):
            continue
        for signal, signal_stats in sorted(stats_by_signal.items()):
            action = _signal_action(str(horizon), str(signal), signal_stats if isinstance(signal_stats, dict) else {})
            if action:
                actions.append(action)
    return actions


def _context_actions(context_stats_json: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for horizon, rows in sorted((context_stats_json or {}).items(), key=lambda item: int(item[0])):
        if not isinstance(rows, list):
            continue
        for row in rows:
            action = _context_action(str(horizon), row if isinstance(row, dict) else {})
            if action:
                actions.append(action)
    return actions


def _context_action(horizon: str, row: dict[str, Any]) -> dict[str, Any] | None:
    signal = _norm_key(row.get("signal_type"))
    if signal in EXCLUDED_SIGNAL_TARGETS:
        return None
    count = int(row.get("count") or 0)
    if count < MIN_CONTEXT_SAMPLES:
        return None
    scope = _context_scope(row)
    action = _signal_action(horizon, signal, row, min_samples=MIN_CONTEXT_SAMPLES)
    if not action or action.get("action") == "hold":
        return None
    action["scope"] = scope
    action["scoped_target"] = scoped_signal_weight_key(signal, **scope)
    return action


def _context_scope(row: dict[str, Any]) -> dict[str, str]:
    return {
        "regime": str(row.get("regime") or "").strip().upper(),
        "lane": _norm_key(row.get("candidate_lane")),
        "entry_type": _norm_key(row.get("entry_type")),
    }


def _signal_action(
    horizon: str,
    signal: str,
    stats: dict[str, Any],
    *,
    min_samples: int = MIN_SIGNAL_SAMPLES,
) -> dict[str, Any] | None:
    if signal in EXCLUDED_SIGNAL_TARGETS:
        return None
    count = int(stats.get("count") or 0)
    if count < min_samples:
        return None
    avg_return = _num(stats.get("avg_return_pct"), 0.0)
    win_rate = _num(stats.get("win_rate_pct"), 0.0)
    big_loss = _num(stats.get("big_loss_rate_pct"), 0.0)
    avg_dd = _num(stats.get("avg_drawdown_pct"), 0.0)
    if avg_return <= -1.0 or win_rate < 45.0 or big_loss >= 35.0 or avg_dd <= -10.0:
        return _action_row("downweight", horizon, signal, stats, _downweight_multiplier(avg_return, big_loss, avg_dd))
    if avg_return >= 2.0 and win_rate >= 60.0 and big_loss <= 25.0:
        return _action_row("upweight", horizon, signal, stats, 1.15)
    return _action_row("hold", horizon, signal, stats, 1.0)


def _action_row(action: str, horizon: str, signal: str, stats: dict[str, Any], multiplier: float) -> dict[str, Any]:
    return {
        "action": action,
        "horizon": horizon,
        "target": signal,
        "weight_multiplier": round(multiplier, 2),
        "evidence": {
            "count": int(stats.get("count") or 0),
            "avg_return_pct": _round(stats.get("avg_return_pct")),
            "win_rate_pct": _round(stats.get("win_rate_pct")),
            "big_loss_rate_pct": _round(stats.get("big_loss_rate_pct")),
            "avg_drawdown_pct": _round(stats.get("avg_drawdown_pct")),
        },
    }


def _downweight_multiplier(avg_return: float, big_loss: float, avg_dd: float) -> float:
    if avg_return <= -3.0 or big_loss >= 50.0 or avg_dd <= -12.0:
        return 0.5
    return 0.75


def _governor_status(shadow_gate: dict[str, Any], signal_actions: list[dict[str, Any]]) -> str:
    shadow_status = str(shadow_gate.get("status") or "insufficient_sample")
    if shadow_status in {"candidate", "reject"}:
        return shadow_status
    if any(item.get("action") in {"downweight", "upweight"} for item in signal_actions):
        return "watch"
    return shadow_status


def _mode_recommendation(shadow_gate: dict[str, Any]) -> str:
    if shadow_gate.get("status") == "candidate":
        return "review_promote_dynamic_policy"
    if shadow_gate.get("status") == "reject":
        return "keep_static_policy"
    return "keep_shadow"


def _summary(shadow_gate: dict[str, Any], signal_actions: list[dict[str, Any]]) -> str:
    down = _unique_targets(signal_actions, "downweight")
    up = _unique_targets(signal_actions, "upweight")
    shadow_text = {
        "candidate": "shadow 新增组显著优于移除组，可进入人工晋级评审",
        "reject": "shadow 新增组未跑赢移除组，继续保持静态策略",
        "watch": "shadow 有改善但未全部过门槛",
    }.get(str(shadow_gate.get("status")), "样本不足，继续 shadow 观察")
    parts = [shadow_text]
    if down:
        parts.append("建议降权 " + "、".join(down[:6]))
    if up:
        parts.append("建议升权 " + "、".join(up[:6]))
    return "；".join(parts)


def _unique_targets(signal_actions: list[dict[str, Any]], action: str) -> list[str]:
    names = []
    for item in signal_actions:
        target = str(item.get("target") or "")
        if item.get("action") == action and target and target not in names:
            names.append(target)
    return names


def _json_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _action_from_recommendation_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("type") == "policy_governor":
        return None
    payload = row.get("reason")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "action": payload.get("action") or row.get("type"),
        "horizon": payload.get("horizon") or row.get("horizon"),
        "target": payload.get("target") or row.get("target"),
        "weight_multiplier": payload.get("weight_multiplier"),
        "scope": payload.get("scope") if isinstance(payload.get("scope"), dict) else {},
    }


def _action_weight_key(action: dict[str, Any]) -> str:
    scope = action.get("scope") if isinstance(action.get("scope"), dict) else {}
    return scoped_signal_weight_key(
        action.get("target"),
        regime=scope.get("regime"),
        lane=scope.get("lane"),
        entry_type=scope.get("entry_type"),
    )


def _bounded_runtime_weight(raw: Any) -> float:
    value = _num(raw)
    if value is None or value <= 0:
        return 1.0
    return round(max(0.4, min(value, 1.3)), 2)


def _bounded_multiplier(raw: Any, action: str) -> float:
    value = _num(raw)
    if value is None:
        return 1.0
    if action == "downweight":
        return round(max(0.4, min(value, 0.95)), 2)
    if action == "upweight":
        return round(max(1.01, min(value, 1.3)), 2)
    value = round(max(0.4, min(value, 1.3)), 2)
    return value if value != 1.0 else 1.0


def _num(raw: Any, default: float | None = None) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _norm_key(raw: Any) -> str:
    return str(raw or "").strip().lower().replace("-", "_").replace(" ", "_") or "unknown"


def _dedup(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _round(raw: Any) -> float | None:
    value = _num(raw)
    return round(value, 2) if value is not None else None
