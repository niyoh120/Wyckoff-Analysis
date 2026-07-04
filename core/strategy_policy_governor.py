"""Policy governance rules for attribution and shadow results."""

from __future__ import annotations

import json
import math
from typing import Any

VERSION = "strategy_policy_governor_v1"
MIN_SIGNAL_SAMPLES = 10
MIN_SHADOW_RUNS = 10
MIN_SHADOW_MATCHED = 3
EXCLUDED_SIGNAL_TARGETS = {"unknown", "shadow_added", "shadow_removed"}


def build_strategy_policy_governor(
    *,
    signal_stats_json: dict[str, Any],
    shadow_diff_stats_json: dict[str, Any],
    horizons: list[int],
) -> dict[str, Any]:
    horizon = _focus_horizon(horizons)
    shadow_gate = _shadow_gate(shadow_diff_stats_json, horizon)
    signal_actions = _signal_actions(signal_stats_json)
    return {
        "version": VERSION,
        "horizon": str(horizon),
        "status": _governor_status(shadow_gate, signal_actions),
        "auto_apply": False,
        "mode_recommendation": _mode_recommendation(shadow_gate),
        "shadow_gate": shadow_gate,
        "signal_actions": signal_actions,
        "summary": _summary(shadow_gate, signal_actions),
    }


def governor_recommendation_rows(governor: dict[str, Any]) -> list[dict[str, str]]:
    rows = [_governor_summary_row(governor)]
    for action in governor.get("signal_actions") or []:
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


def _signal_action(horizon: str, signal: str, stats: dict[str, Any]) -> dict[str, Any] | None:
    if signal in EXCLUDED_SIGNAL_TARGETS:
        return None
    count = int(stats.get("count") or 0)
    if count < MIN_SIGNAL_SAMPLES:
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


def _num(raw: Any, default: float | None = None) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _round(raw: Any) -> float | None:
    value = _num(raw)
    return round(value, 2) if value is not None else None
