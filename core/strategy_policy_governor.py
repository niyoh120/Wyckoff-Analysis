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
    score_bucket_stats_json: dict[str, Any] | None = None,
    shadow_diff_stats_json: dict[str, Any],
    backtest_confirmation_json: dict[str, Any] | None = None,
    formal_dynamic_approval_json: dict[str, Any] | None = None,
    horizons: list[int],
) -> dict[str, Any]:
    horizon = _focus_horizon(horizons)
    shadow_gate = _shadow_gate(shadow_diff_stats_json, horizon)
    signal_actions = _signal_actions(signal_stats_json)
    context_actions = _context_actions(signal_context_stats_json or {})
    selection_actions = _selection_actions(score_bucket_stats_json or {})
    all_actions = signal_actions + context_actions
    promotion_checklist = _promotion_checklist(
        shadow_gate, all_actions, selection_actions, backtest_confirmation_json or {}
    )
    formal_approval = _formal_dynamic_manual_approval(formal_dynamic_approval_json or {})
    next_action = _next_action(shadow_gate, all_actions, promotion_checklist, formal_approval)
    return {
        "version": VERSION,
        "horizon": str(horizon),
        "status": _governor_status(shadow_gate, all_actions),
        "auto_apply": False,
        "formal_dynamic_allowed": _formal_dynamic_allowed(shadow_gate, promotion_checklist, formal_approval),
        "formal_dynamic_approval": _formal_dynamic_approval_status(shadow_gate, promotion_checklist, formal_approval),
        "formal_dynamic_block_reason": _formal_dynamic_block_reason(shadow_gate, promotion_checklist, formal_approval),
        "formal_dynamic_manual_approval": formal_approval,
        "mode_recommendation": _mode_recommendation(shadow_gate),
        "next_action": next_action,
        "next_action_summary": _next_action_summary(next_action),
        "promotion_status": _promotion_status(shadow_gate, formal_approval),
        "promotion_checklist": promotion_checklist,
        "shadow_gate": shadow_gate,
        "signal_actions": signal_actions,
        "context_actions": context_actions,
        "selection_actions": selection_actions,
        "summary": _summary(shadow_gate, signal_actions, selection_actions),
    }


def governor_recommendation_rows(governor: dict[str, Any]) -> list[dict[str, str]]:
    rows = [_governor_summary_row(governor)]
    actions = (
        (governor.get("signal_actions") or [])
        + (governor.get("context_actions") or [])
        + (governor.get("selection_actions") or [])
    )
    for action in actions:
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
                "next_action": governor.get("next_action"),
                "next_action_summary": governor.get("next_action_summary"),
                "promotion_status": governor.get("promotion_status"),
                "promotion_checklist": governor.get("promotion_checklist"),
                "formal_dynamic_allowed": governor.get("formal_dynamic_allowed"),
                "formal_dynamic_approval": governor.get("formal_dynamic_approval"),
                "formal_dynamic_block_reason": governor.get("formal_dynamic_block_reason"),
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


def _selection_actions(score_bucket_stats_json: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for bucket_key, category in (
        ("_selection_mode", "selection_mode"),
        ("_strategy_version", "strategy_version"),
        ("_candidate_lane", "candidate_lane"),
        ("_entry_type", "entry_type"),
    ):
        bucket = score_bucket_stats_json.get(bucket_key)
        if not isinstance(bucket, dict):
            continue
        actions.extend(_selection_bucket_actions(bucket, category))
    return actions


def _selection_bucket_actions(bucket: dict[str, Any], category: str) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for horizon, stats_by_value in sorted(bucket.items(), key=lambda item: int(item[0])):
        if not isinstance(stats_by_value, dict):
            continue
        for value, value_stats in sorted(stats_by_value.items()):
            action = _selection_action(
                str(horizon), category, str(value), value_stats if isinstance(value_stats, dict) else {}
            )
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


def _selection_action(horizon: str, category: str, value: str, stats: dict[str, Any]) -> dict[str, Any] | None:
    if value in EXCLUDED_SIGNAL_TARGETS:
        return None
    count = int(stats.get("count") or 0)
    if count < MIN_CONTEXT_SAMPLES:
        return None
    avg_return = _num(stats.get("avg_return_pct"), 0.0)
    win_rate = _num(stats.get("win_rate_pct"), 0.0)
    big_loss = _num(stats.get("big_loss_rate_pct"), 0.0)
    avg_dd = _num(stats.get("avg_drawdown_pct"), 0.0)
    if avg_return <= -1.0 or win_rate < 45.0 or big_loss >= 35.0 or avg_dd <= -10.0:
        return _selection_action_row(
            "selection_downweight",
            horizon,
            category,
            value,
            stats,
            _downweight_multiplier(avg_return, big_loss, avg_dd),
        )
    if avg_return >= 2.0 and win_rate >= 60.0 and big_loss <= 25.0:
        return _selection_action_row("selection_upweight", horizon, category, value, stats, 1.15)
    return None


def _selection_action_row(
    action: str,
    horizon: str,
    category: str,
    value: str,
    stats: dict[str, Any],
    multiplier: float,
) -> dict[str, Any]:
    row = _action_row(action, horizon, f"{category}={value}", stats, multiplier)
    row["category"] = category
    row["group_value"] = value
    row["recommendation"] = "降级到 shadow/人工复核" if action == "selection_downweight" else "进入人工晋级复核"
    return row


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


def _next_action(
    shadow_gate: dict[str, Any],
    actions: list[dict[str, Any]],
    checklist: list[dict[str, str]],
    formal_approval: dict[str, Any],
) -> str:
    status = str(shadow_gate.get("status") or "")
    if status == "candidate":
        backtest_status = _check_status(checklist, "backtest_confirmation")
        if backtest_status == "fail":
            return "keep_shadow_backtest_failed"
        if backtest_status != "pass":
            return "run_backtest_confirmation"
        if (
            _check_status(checklist, "signal_actions") == "review"
            or _check_status(checklist, "selection_actions") == "review"
        ):
            return "review_policy_actions"
        if formal_approval.get("status") == "approved":
            return "formal_dynamic_approved"
        return "manual_review_dynamic_on"
    if status == "reject":
        return "keep_static_policy"
    if status == "insufficient_sample":
        return "collect_more_shadow_samples"
    if any(item.get("action") in {"downweight", "upweight"} for item in actions):
        return "keep_shadow_apply_signal_weights"
    return "keep_shadow_observe"


def _next_action_summary(next_action: str) -> str:
    summaries = {
        "manual_review_dynamic_on": "shadow 新增组已跑赢移除组；先完成晋级清单和回测复核，再人工决定 dynamic=on。",
        "run_backtest_confirmation": "shadow 新增组已跑赢移除组；先补齐最新回测确认，再进入人工晋级评审。",
        "keep_shadow_backtest_failed": "shadow 新增组已跑赢移除组，但回测确认未通过；保持 shadow，不晋级 dynamic=on。",
        "review_policy_actions": "shadow 与回测已满足候选条件；先复核信号调权/候选源治理，再人工决定 dynamic=on。",
        "formal_dynamic_approved": "shadow、回测、治理项与人工批准均完成；FUNNEL_DYNAMIC_POLICY=on 时可进入正式漏斗。",
        "keep_static_policy": "shadow 新增组未证明优于移除组；保持静态策略，不晋级 dynamic=on。",
        "collect_more_shadow_samples": "shadow 样本不足；继续收集 shadow run 与命中结果。",
        "keep_shadow_apply_signal_weights": "保持 shadow；信号级调权可继续用于尾盘和漏斗 shadow。",
        "keep_shadow_observe": "保持 shadow 观察，不调整生产策略。",
    }
    return summaries.get(next_action, "保持 shadow 观察，不调整生产策略。")


def _promotion_status(shadow_gate: dict[str, Any], formal_approval: dict[str, Any]) -> str:
    status = str(shadow_gate.get("status") or "")
    if status == "candidate":
        if formal_approval.get("status") == "approved":
            return "manual_approved"
        return "manual_review_required"
    if status == "reject":
        return "do_not_promote"
    if status == "insufficient_sample":
        return "collect_more_samples"
    return "keep_shadow"


def _formal_dynamic_allowed(
    shadow_gate: dict[str, Any],
    checklist: list[dict[str, str]],
    formal_approval: dict[str, Any],
) -> bool:
    return (
        shadow_gate.get("status") == "candidate"
        and not _formal_dynamic_checklist_block(checklist)
        and formal_approval.get("status") == "approved"
    )


def _formal_dynamic_approval_status(
    shadow_gate: dict[str, Any],
    checklist: list[dict[str, str]],
    formal_approval: dict[str, Any],
) -> str:
    status = str(shadow_gate.get("status") or "")
    if status == "candidate":
        block = _formal_dynamic_checklist_block(checklist)
        if block:
            return block
        if formal_approval.get("status") == "approved":
            return "manual_approved"
        if formal_approval.get("status") == "incomplete":
            return "manual_approval_incomplete"
        return "manual_review_required"
    if status == "reject":
        return "not_approved"
    if status == "insufficient_sample":
        return "insufficient_shadow_sample"
    return "keep_shadow"


def _formal_dynamic_block_reason(
    shadow_gate: dict[str, Any],
    checklist: list[dict[str, str]],
    formal_approval: dict[str, Any],
) -> str:
    status = str(shadow_gate.get("status") or "")
    if status == "candidate":
        block = _formal_dynamic_checklist_block(checklist)
        if block:
            return block
        if formal_approval.get("status") == "approved":
            return ""
        if formal_approval.get("status") == "incomplete":
            return "manual_approval_incomplete"
        return "manual_review_required"
    if status == "reject":
        return "shadow_rejected"
    if status == "insufficient_sample":
        return "insufficient_shadow_sample"
    return "keep_shadow"


def _formal_dynamic_manual_approval(raw: dict[str, Any]) -> dict[str, Any]:
    approved = _truthy(raw.get("approved"))
    approved_by = str(raw.get("approved_by") or raw.get("operator") or "").strip()
    reason = str(raw.get("reason") or raw.get("summary") or "").strip()
    status = "approved" if approved and approved_by and reason else "incomplete" if approved else "missing"
    return {
        "status": status,
        "approved": status == "approved",
        "approved_by": approved_by,
        "reason": reason,
        "approved_at": str(raw.get("approved_at") or raw.get("timestamp") or "").strip(),
    }


def _truthy(raw: Any) -> bool:
    if raw is True:
        return True
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y", "approved"}
    return raw == 1


def _promotion_checklist(
    shadow_gate: dict[str, Any],
    actions: list[dict[str, Any]],
    selection_actions: list[dict[str, Any]],
    backtest_confirmation: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        _shadow_sample_check(shadow_gate),
        _shadow_performance_check(shadow_gate),
        _signal_action_check(actions),
        _selection_action_check(selection_actions),
        _backtest_confirmation_check(shadow_gate, backtest_confirmation),
    ]


def _shadow_sample_check(shadow_gate: dict[str, Any]) -> dict[str, str]:
    runs = int(shadow_gate.get("run_count") or 0)
    added = int(shadow_gate.get("added_matched") or 0)
    removed = int(shadow_gate.get("removed_matched") or 0)
    passed = runs >= MIN_SHADOW_RUNS and added >= MIN_SHADOW_MATCHED and removed >= MIN_SHADOW_MATCHED
    return {
        "key": "shadow_sample",
        "status": "pass" if passed else "fail",
        "summary": (
            f"shadow run {runs}/{MIN_SHADOW_RUNS}，新增命中 {added}/{MIN_SHADOW_MATCHED}，"
            f"移除命中 {removed}/{MIN_SHADOW_MATCHED}"
        ),
    }


def _shadow_performance_check(shadow_gate: dict[str, Any]) -> dict[str, str]:
    status = str(shadow_gate.get("status") or "")
    if status == "candidate":
        check_status = "pass"
    elif status == "reject":
        check_status = "fail"
    else:
        check_status = "review"
    return {
        "key": "shadow_performance",
        "status": check_status,
        "summary": (
            f"收益差 {shadow_gate.get('return_lift_pct', '-')}，"
            f"胜率差 {shadow_gate.get('win_rate_lift_pct', '-')}，"
            f"回撤差 {shadow_gate.get('drawdown_lift_pct', '-')}"
        ),
    }


def _signal_action_check(actions: list[dict[str, Any]]) -> dict[str, str]:
    active = [item for item in actions if item.get("action") in {"downweight", "upweight"}]
    return {
        "key": "signal_actions",
        "status": "review" if active else "pass",
        "summary": f"{len(active)} 个 scoped 信号调权需要一致性复核",
    }


def _selection_action_check(actions: list[dict[str, Any]]) -> dict[str, str]:
    active = [item for item in actions if item.get("action") in {"selection_downweight", "selection_upweight"}]
    return {
        "key": "selection_actions",
        "status": "review" if active else "pass",
        "summary": f"{len(active)} 个候选源治理动作需要一致性复核",
    }


def _backtest_confirmation_check(shadow_gate: dict[str, Any], confirmation: dict[str, Any]) -> dict[str, str]:
    if shadow_gate.get("status") != "candidate":
        return {
            "key": "backtest_confirmation",
            "status": "not_required",
            "summary": "未进入 dynamic 晋级候选，暂不要求回测确认",
        }
    status = _normalized_backtest_status(confirmation)
    if status:
        return {
            "key": "backtest_confirmation",
            "status": status,
            "summary": _backtest_confirmation_summary(confirmation, status),
        }
    return {
        "key": "backtest_confirmation",
        "status": "review",
        "summary": "切换 dynamic=on 前需要最新回测或实盘观察确认",
    }


def _normalized_backtest_status(confirmation: dict[str, Any]) -> str:
    status = str(confirmation.get("status") or confirmation.get("result") or "").strip().lower()
    aliases = {
        "approved": "pass",
        "passed": "pass",
        "ok": "pass",
        "success": "pass",
        "rejected": "fail",
        "failed": "fail",
        "block": "fail",
        "blocked": "fail",
    }
    status = aliases.get(status, status)
    if status == "pass" and confirmation.get("strategy_policy_ready") is not True:
        return "review"
    return status if status in {"pass", "fail", "review"} else ""


def _backtest_confirmation_summary(confirmation: dict[str, Any], status: str) -> str:
    if status == "review" and confirmation.get("strategy_policy_ready") is not True:
        reason = str(confirmation.get("strategy_policy_reason") or "缺少策略治理口径证据").strip()
        return f"回测结果仍需人工复核：{reason}"
    summary = str(confirmation.get("summary") or confirmation.get("note") or "").strip()
    if summary:
        return summary
    source = str(confirmation.get("source") or "backtest").strip()
    report_date = str(confirmation.get("report_date") or confirmation.get("date") or "").strip()
    suffix = f"，报告 {report_date}" if report_date else ""
    labels = {"pass": "回测确认通过", "fail": "回测确认未通过", "review": "回测结果仍需人工复核"}
    return f"{source} {labels.get(status, '回测确认待复核')}{suffix}"


def _formal_dynamic_checklist_block(checklist: list[dict[str, str]]) -> str:
    backtest_block = _checklist_row_block(checklist, "backtest_confirmation")
    if backtest_block:
        return backtest_block
    for row in checklist:
        key = str(row.get("key") or "").strip()
        if key == "backtest_confirmation":
            continue
        block = _checklist_row_block(checklist, key)
        if block:
            return block
    return ""


def _checklist_row_block(checklist: list[dict[str, str]], key: str) -> str:
    status = _check_status(checklist, key)
    if status == "fail":
        return f"{key}_failed"
    if status == "review":
        if key == "backtest_confirmation":
            if "策略治理口径证据" in _check_summary(checklist, key):
                return "backtest_policy_evidence_required"
            return "backtest_confirmation_required"
        return f"{key}_review_required"
    if status in {"", "missing", "unknown"}:
        return f"{key}_missing"
    return ""


def _check_status(checklist: list[dict[str, str]], key: str) -> str:
    for row in checklist:
        if str(row.get("key") or "") == key:
            return str(row.get("status") or "unknown").strip().lower()
    return ""


def _check_summary(checklist: list[dict[str, str]], key: str) -> str:
    for row in checklist:
        if str(row.get("key") or "") == key:
            return str(row.get("summary") or "").strip()
    return ""


def _summary(
    shadow_gate: dict[str, Any],
    signal_actions: list[dict[str, Any]],
    selection_actions: list[dict[str, Any]] | None = None,
) -> str:
    down = _unique_targets(signal_actions, "downweight")
    up = _unique_targets(signal_actions, "upweight")
    selection_down = _unique_targets(selection_actions or [], "selection_downweight")
    selection_up = _unique_targets(selection_actions or [], "selection_upweight")
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
    if selection_down:
        parts.append("候选源降级复核 " + "、".join(selection_down[:4]))
    if selection_up:
        parts.append("候选源晋级复核 " + "、".join(selection_up[:4]))
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
    return 1.0


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
