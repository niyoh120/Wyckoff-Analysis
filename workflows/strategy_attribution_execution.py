"""Execution-state helpers for strategy attribution policy outputs."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from core.strategy_policy_display import (
    format_policy_signal_label,
    policy_formal_dynamic_label,
    policy_next_action_label,
    safe_policy_weight,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FUNNEL_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "wyckoff_funnel.yml"


def attribution_execution_state(
    governor: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    workflow_path: Path | None = None,
) -> dict[str, Any]:
    mode = funnel_dynamic_policy_mode(workflow_path=workflow_path)
    horizon = str(governor.get("horizon") or "5")
    action_details = _action_details(actions, horizon=horizon)
    selection_details = _selection_action_details(actions, horizon=horizon)
    action_count = len(action_details)
    formal_allowed = attribution_formal_dynamic_allowed(governor)
    if action_count <= 0:
        scope = "none"
        summary = "暂无可执行信号调权。"
    elif mode == "on" and formal_allowed:
        scope = "funnel_formal"
        summary = f"h={horizon} 信号级调权会影响漏斗正式候选。"
    elif mode in {"on", "shadow"}:
        scope = "funnel_shadow"
        summary = f"h={horizon} 信号级调权用于漏斗动态策略 shadow 对照；治理器未批准进入正式 dynamic。"
    else:
        scope = "none"
        summary = f"h={horizon} 信号级调权暂无下游消费方；漏斗动态策略当前关闭。"
    state = {
        "funnel_dynamic_policy": mode,
        "horizon": horizon,
        "signal_action_count": action_count,
        "action_details": action_details,
        "selection_action_count": len(selection_details),
        "selection_action_details": selection_details,
        "next_action": governor.get("next_action", "keep_shadow_observe"),
        "next_action_summary": governor.get("next_action_summary", "-"),
        "formal_dynamic_allowed": formal_allowed,
        "formal_dynamic_block_reason": _formal_dynamic_block_reason(governor, formal_allowed),
        "promotion_status": governor.get("promotion_status", "unknown"),
        "promotion_checklist": governor.get("promotion_checklist")
        if isinstance(governor.get("promotion_checklist"), list)
        else [],
        "scope": scope,
        "summary": _auto_apply_note(summary, governor),
    }
    state.update(attribution_active_scope_flags(state))
    return state


def attribution_formal_dynamic_allowed(governor: dict[str, Any]) -> bool:
    explicit = _bool_value(governor.get("formal_dynamic_allowed"))
    if explicit is False:
        return False
    if explicit is True:
        return _promotion_checklist_ready(governor)
    approval = str(governor.get("formal_dynamic_approval") or governor.get("approval_status") or "").strip().lower()
    if approval in {"approved", "manual_approved", "dynamic_on_approved", "formal_dynamic_approved"}:
        return _promotion_checklist_ready(governor)
    if approval in {"rejected", "blocked", "not_approved"}:
        return False
    next_action = str(governor.get("next_action") or "").strip()
    return (
        bool(governor.get("auto_apply"))
        and next_action == "manual_review_dynamic_on"
        and _promotion_checklist_ready(governor)
    )


def attribution_active_scope_flags(execution: dict[str, Any]) -> dict[str, Any]:
    action_count = int(execution.get("signal_action_count") or 0)
    scope = str(execution.get("scope") or "none").strip()
    shadow_active = action_count > 0 and scope == "funnel_shadow"
    formal_active = action_count > 0 and scope == "funnel_formal"
    labels = []
    if formal_active:
        labels.append("正式漏斗")
    elif shadow_active:
        labels.append("漏斗shadow")
    return {
        "active_scope": "+".join(labels) or "无",
        "funnel_shadow_weights_active": shadow_active,
        "funnel_formal_weights_active": formal_active,
    }


def funnel_dynamic_policy_mode(*, workflow_path: Path | None = None) -> str:
    raw = os.getenv("FUNNEL_DYNAMIC_POLICY")
    if raw is not None:
        return _normalize_mode(raw)
    path = workflow_path or DEFAULT_FUNNEL_WORKFLOW_PATH
    return _workflow_default_mode(path) or "shadow"


def _workflow_default_mode(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        if "FUNNEL_DYNAMIC_POLICY:" not in line:
            continue
        fallback = re.search(r"\|\|\s*['\"]([A-Za-z_]+)['\"]\s*}}", line)
        if fallback:
            return _normalize_mode(fallback.group(1))
        literal = re.search(r"FUNNEL_DYNAMIC_POLICY:\s*['\"]?([A-Za-z_]+)['\"]?", line)
        if literal:
            return _normalize_mode(literal.group(1))
    return ""


def _action_details(actions: list[dict[str, Any]], *, horizon: str) -> list[dict[str, Any]]:
    details = []
    for item in actions:
        action = _action_from_item(item)
        if action in {"downweight", "upweight"} and _horizon_from_item(item) == horizon:
            details.append(_action_detail(item, action))
    return details


def _selection_action_details(actions: list[dict[str, Any]], *, horizon: str) -> list[dict[str, Any]]:
    details = []
    for item in actions:
        action = _action_from_item(item)
        if action in {"selection_downweight", "selection_upweight"} and _horizon_from_item(item) == horizon:
            details.append(_selection_action_detail(item, action))
    return details


def _action_detail(item: dict[str, Any], action: str) -> dict[str, Any]:
    payload = _json_payload(item.get("reason"))
    scope = _scope_from_item(item, payload)
    target = str(item.get("target") or payload.get("target") or "").strip()
    return {
        "action": action,
        "horizon": _horizon_from_item(item),
        "target": target,
        "label": format_policy_signal_label(target, scope),
        "weight_multiplier": safe_policy_weight(payload.get("weight_multiplier", item.get("weight_multiplier"))),
        "scope": scope,
        "evidence": _evidence_from_item(item, payload),
    }


def _selection_action_detail(item: dict[str, Any], action: str) -> dict[str, Any]:
    payload = _json_payload(item.get("reason"))
    target = str(item.get("target") or payload.get("target") or "").strip()
    return {
        "action": action,
        "horizon": _horizon_from_item(item),
        "target": target,
        "label": target,
        "weight_multiplier": safe_policy_weight(payload.get("weight_multiplier", item.get("weight_multiplier"))),
        "recommendation": str(payload.get("recommendation") or item.get("recommendation") or ""),
        "category": str(payload.get("category") or item.get("category") or ""),
        "group_value": str(payload.get("group_value") or item.get("group_value") or ""),
        "evidence": _evidence_from_item(item, payload),
    }


def attribution_operations_brief(
    shadow: dict[str, Any],
    execution: dict[str, Any],
    *,
    max_actions: int = 8,
) -> dict[str, Any]:
    latest = shadow.get("latest") if isinstance(shadow.get("latest"), dict) else {}
    actions = [row for row in execution.get("action_details") or [] if isinstance(row, dict)]
    selection_actions = [row for row in execution.get("selection_action_details") or [] if isinstance(row, dict)]
    limited_actions = actions[: max(int(max_actions), 0)]
    limited_selection_actions = selection_actions[: max(int(max_actions), 0)]
    action_summary = _action_summary(limited_actions, total=len(actions))
    selection_action_summary = _selection_action_summary(limited_selection_actions, total=len(selection_actions))
    checklist = _promotion_checklist(execution)
    backtest_confirmation = _checklist_item_brief(checklist, "backtest_confirmation")
    return {
        "latest_shadow": _latest_shadow_brief(latest),
        "next_action": execution.get("next_action", "keep_shadow_observe"),
        "next_action_summary": execution.get("next_action_summary", "-"),
        "scope": execution.get("scope", "none"),
        "active_scope": _execution_active_scope_text(execution),
        "formal_dynamic_allowed": bool(execution.get("formal_dynamic_allowed")),
        "formal_dynamic_block_reason": execution.get("formal_dynamic_block_reason", ""),
        "promotion_checklist_summary": _checklist_summary(checklist),
        "promotion_blockers": _checklist_blockers(checklist),
        "backtest_confirmation": backtest_confirmation,
        "backtest_confirmation_text": _checklist_item_text(backtest_confirmation),
        "action_count": len(actions),
        "action_details": limited_actions,
        "action_summary": action_summary,
        "selection_action_count": len(selection_actions),
        "selection_action_details": limited_selection_actions,
        "selection_action_summary": selection_action_summary,
        "operator_summary": _operator_summary(
            _latest_shadow_brief(latest), execution, action_summary, selection_action_summary, backtest_confirmation
        ),
    }


def _scope_from_item(item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("scope"), dict):
        return payload["scope"]
    return item.get("scope") if isinstance(item.get("scope"), dict) else {}


def _evidence_from_item(item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("evidence"), dict):
        return payload["evidence"]
    return item.get("evidence") if isinstance(item.get("evidence"), dict) else {}


def _latest_shadow_brief(latest: dict[str, Any]) -> dict[str, Any]:
    if not latest:
        return {}
    selection = latest.get("selection_summary") if isinstance(latest.get("selection_summary"), dict) else {}
    return {
        "trade_date": latest.get("trade_date"),
        "regime": latest.get("regime"),
        "base_count": selection.get("base_count"),
        "shadow_count": selection.get("shadow_count"),
        "diff_added_count": selection.get("diff_added_count"),
        "diff_removed_count": selection.get("diff_removed_count"),
        "jaccard": selection.get("jaccard"),
        "diff_added_sample": latest.get("diff_added_sample") or [],
        "diff_removed_sample": latest.get("diff_removed_sample") or [],
    }


def _operator_summary(
    latest: dict[str, Any],
    execution: dict[str, Any],
    action_summary: str,
    selection_action_summary: str,
    backtest_confirmation: dict[str, str],
) -> str:
    return "；".join(
        [
            f"下一步={execution.get('next_action_summary') or execution.get('next_action') or '-'}",
            f"作用范围={_execution_active_scope_text(execution)}",
            _formal_dynamic_summary(execution),
            f"回测确认={_checklist_item_text(backtest_confirmation)}",
            _shadow_summary(latest),
            action_summary,
            selection_action_summary,
        ]
    )


def _promotion_checklist(execution: dict[str, Any]) -> list[dict[str, str]]:
    rows = execution.get("promotion_checklist")
    if not isinstance(rows, list):
        return []
    return [_checklist_item_brief(rows, str(row.get("key") or "")) for row in rows if isinstance(row, dict)]


def _checklist_item_brief(rows: list[dict[str, Any]], key: str) -> dict[str, str]:
    for row in rows:
        if not isinstance(row, dict) or str(row.get("key") or "") != key:
            continue
        return {
            "key": key,
            "status": str(row.get("status") or "unknown"),
            "summary": str(row.get("summary") or "-"),
        }
    return {"key": key, "status": "missing", "summary": "缺少检查项"}


def _checklist_summary(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "晋级清单=无"
    return "；".join(
        f"{_checklist_label(row.get('key', ''))}={_status_label(row.get('status') or 'unknown')}" for row in rows
    )


def _checklist_blockers(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("status") in {"fail", "review", "missing", "unknown"}]


def _checklist_item_text(row: dict[str, str]) -> str:
    status = row.get("status") or "unknown"
    summary = row.get("summary") or "-"
    return f"{_status_label(status)}({summary})"


def _checklist_label(key: str) -> str:
    labels = {
        "shadow_sample": "样本",
        "shadow_added_outperforms_removed": "新增跑赢",
        "selection_actions": "候选源治理",
        "signal_actions": "信号调权",
        "backtest_confirmation": "回测",
    }
    return labels.get(key, key or "-")


def _status_label(status: str) -> str:
    labels = {
        "pass": "通过",
        "fail": "失败",
        "review": "待复核",
        "missing": "缺失",
        "not_required": "不需要",
        "unknown": "未知",
    }
    return labels.get(status, status or "未知")


def _execution_active_scope_text(execution: dict[str, Any]) -> str:
    explicit = str(execution.get("active_scope") or "").strip()
    if explicit:
        return explicit
    return str(attribution_active_scope_flags(execution)["active_scope"])


def _formal_dynamic_summary(execution: dict[str, Any]) -> str:
    return f"正式dynamic={policy_formal_dynamic_label(execution)}"


def _shadow_summary(latest: dict[str, Any]) -> str:
    if not latest:
        return "Shadow=暂无最新对照"
    return (
        f"Shadow={latest.get('trade_date', '-')} {latest.get('regime', '-')} "
        f"新增{latest.get('diff_added_count', '-')} 移除{latest.get('diff_removed_count', '-')}"
    )


def _action_summary(actions: list[dict[str, Any]], *, total: int) -> str:
    if total <= 0:
        return "本期暂无可执行调权。"
    parts = [
        f"{row.get('label', row.get('target', '-'))}×{safe_policy_weight(row.get('weight_multiplier')):.2f}"
        for row in actions[:4]
    ]
    suffix = f"，另 {total - len(actions)} 项" if total > len(actions) else ""
    return f"本期 {total} 个 scoped 调权：" + "，".join(parts) + suffix


def _selection_action_summary(actions: list[dict[str, Any]], *, total: int) -> str:
    if total <= 0:
        return "候选源治理=无"
    parts = []
    for row in actions[:4]:
        label = str(row.get("label") or row.get("target") or "-")
        recommendation = str(row.get("recommendation") or _selection_recommendation_label(row.get("action"))).strip()
        parts.append(f"{label} {recommendation}×{safe_policy_weight(row.get('weight_multiplier')):.2f}")
    suffix = f"，另 {total - len(actions)} 项" if total > len(actions) else ""
    return f"候选源治理 {total} 项：" + "，".join(parts) + suffix


def _selection_recommendation_label(action: Any) -> str:
    if str(action or "") == "selection_downweight":
        return "降级到 shadow/人工复核"
    if str(action or "") == "selection_upweight":
        return "进入人工晋级复核"
    return "人工复核"


def _action_from_item(item: dict[str, Any]) -> str:
    if item.get("type") == "policy_governor":
        return ""
    payload = _json_payload(item.get("reason"))
    return str(item.get("action") or item.get("type") or payload.get("action") or "").strip()


def _horizon_from_item(item: dict[str, Any]) -> str:
    payload = _json_payload(item.get("reason"))
    return str(item.get("horizon") or payload.get("horizon") or "").strip()


def _json_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_mode(raw: object) -> str:
    mode = str(raw or "").strip().lower()
    return mode if mode in {"off", "shadow", "on"} else "off"


def _auto_apply_note(summary: str, governor: dict[str, Any]) -> str:
    if governor.get("formal_dynamic_allowed") is True:
        return summary
    if governor.get("auto_apply"):
        return summary
    next_action = str(governor.get("next_action") or "").strip()
    label = policy_next_action_label(next_action)
    return (
        summary
        + " 策略治理器不会自动把 FUNNEL_DYNAMIC_POLICY 晋级到 on；"
        + f"下一步是{label}（追证据字段: {next_action or '无'}）。"
    )


def _formal_dynamic_block_reason(governor: dict[str, Any], allowed: bool) -> str:
    if allowed:
        return ""
    explicit_reason = str(governor.get("formal_dynamic_block_reason") or "").strip()
    if explicit_reason:
        return explicit_reason
    explicit = _bool_value(governor.get("formal_dynamic_allowed"))
    if explicit is True:
        return _promotion_checklist_block_reason(governor) or "formal_dynamic_checklist_not_ready"
    if explicit is False:
        return "formal_dynamic_allowed=false"
    next_action = str(governor.get("next_action") or "").strip()
    if next_action and next_action != "manual_review_dynamic_on":
        return f"next_action={next_action}"
    if not bool(governor.get("auto_apply")):
        return "auto_apply=false"
    checklist_block = _promotion_checklist_block_reason(governor)
    if checklist_block:
        return checklist_block
    status = str(governor.get("promotion_status") or governor.get("status") or "unknown").strip()
    return f"promotion_status={status}"


def _bool_value(value: Any) -> bool | None:
    if value is True or value is False:
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None


def _promotion_checklist_ready(governor: dict[str, Any]) -> bool:
    rows = governor.get("promotion_checklist")
    if not isinstance(rows, list) or not rows:
        return False
    return not _promotion_checklist_block_reason(governor)


def _promotion_checklist_block_reason(governor: dict[str, Any]) -> str:
    rows = governor.get("promotion_checklist")
    if not isinstance(rows, list) or not rows:
        return "promotion_checklist=missing"
    blocked = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        if status not in {"pass", "not_required"}:
            blocked.append(f"{row.get('key', 'unknown')}:{status or 'unknown'}")
    return f"promotion_checklist={','.join(blocked)}" if blocked else ""
