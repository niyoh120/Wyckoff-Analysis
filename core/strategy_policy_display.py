"""Display helpers for strategy policy weights."""

from __future__ import annotations

import math
from typing import Any


def policy_weight_rows(weights: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    for key, raw_weight in sorted((weights or {}).items()):
        parsed = parse_policy_weight_key(key)
        weight = safe_policy_weight(raw_weight)
        rows.append(
            {
                "key": str(key),
                "signal_type": parsed["signal_type"],
                "scope": parsed["scope"],
                "label": format_policy_signal_label(parsed["signal_type"], parsed["scope"]),
                "weight": weight,
                "direction": "down" if weight < 1.0 else "up" if weight > 1.0 else "flat",
            }
        )
    return rows


def format_policy_weight_text(weights: dict[str, Any] | None, *, limit: int = 8, delimiter: str = "，") -> str:
    rows = policy_weight_rows(weights)
    parts = [_format_weight_row(row) for row in rows[: max(int(limit), 0)]]
    if len(rows) > limit:
        parts.append(f"等{len(rows)}项")
    return delimiter.join(parts)


def format_policy_meta_text(meta: dict[str, Any] | None) -> str:
    if not isinstance(meta, dict) or not meta:
        return ""
    tokens = _policy_source_tokens(meta)
    active = _policy_active_scope(meta)
    if active:
        tokens.append(f"范围={active}")
    formal_block = str(meta.get("formal_dynamic_block_reason") or "").strip()
    if meta.get("formal_dynamic_allowed") is False and formal_block:
        tokens.append(f"正式dynamic={policy_formal_dynamic_label(meta)}")
    backtest = str(meta.get("backtest_confirmation_text") or "").strip()
    if backtest:
        tokens.append(f"回测={backtest}")
    checklist = str(meta.get("promotion_checklist_summary") or "").strip()
    if checklist:
        tokens.append(f"晋级={checklist}")
    return f"（{', '.join(tokens)}）" if tokens else ""


def parse_policy_weight_key(raw: Any) -> dict[str, Any]:
    parts = [part.strip() for part in str(raw or "").split("|") if part.strip()]
    signal = parts[0] if parts else ""
    scope: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        scope[_scope_key(key)] = value
    return {"signal_type": signal, "scope": scope}


def format_policy_signal_label(signal_type: Any, scope: dict[str, Any] | None = None) -> str:
    signal = str(signal_type or "").strip() or "unknown"
    scope_text = format_policy_scope(scope)
    return f"{signal}[{scope_text}]" if scope_text else signal


def format_policy_scope(scope: dict[str, Any] | None) -> str:
    row = scope or {}
    parts = []
    regime = str(row.get("regime") or "").strip()
    lane = str(row.get("lane") or "").strip()
    entry = str(row.get("entry_type") or row.get("entry") or "").strip()
    if regime:
        parts.append(f"regime={regime}")
    if lane:
        parts.append(f"lane={lane}")
    if entry:
        parts.append(f"entry={entry}")
    return ", ".join(parts)


def safe_policy_weight(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return value if math.isfinite(value) else 1.0


def _format_weight_row(row: dict[str, Any]) -> str:
    marker = "↓" if row.get("direction") == "down" else "↑" if row.get("direction") == "up" else ""
    return f"{row.get('label')}×{safe_policy_weight(row.get('weight')):.2f}{marker}"


def _policy_source_tokens(meta: dict[str, Any]) -> list[str]:
    tokens = []
    source = str(meta.get("source") or "").strip()
    report_date = str(meta.get("report_date") or "").strip()
    horizon = str(meta.get("horizon") or "").strip()
    if source:
        tokens.append(source)
    if report_date:
        tokens.append(f"报告={report_date}")
    if horizon:
        tokens.append(f"周期=h{horizon}")
    age = meta.get("age_days")
    if age is not None and str(age) != "":
        tokens.append(f"距今={age}天")
    execution_policy = str(meta.get("execution_policy") or "").strip()
    if execution_policy:
        tokens.append(f"策略={policy_execution_mode_label(execution_policy)}")
    next_action = str(meta.get("next_action") or "").strip()
    if next_action:
        tokens.append(f"下一步={policy_next_action_label(next_action)}")
    return tokens


def _policy_active_scope(meta: dict[str, Any]) -> str:
    explicit = str(meta.get("active_scope") or meta.get("policy_weight_active_scope") or "").strip()
    if explicit and explicit != "无":
        return explicit
    parts = []
    if meta.get("tail_buy_weights_active") is True:
        parts.append("尾盘")
    if meta.get("funnel_formal_weights_active") is True:
        parts.append("正式漏斗")
    elif meta.get("funnel_shadow_weights_active") is True:
        parts.append("漏斗shadow")
    if parts:
        return "+".join(parts)
    scope = str(meta.get("execution_scope") or meta.get("policy_weight_execution_scope") or "").strip()
    if scope == "tail_buy_and_funnel":
        return "尾盘+正式漏斗"
    if scope == "tail_buy_and_funnel_shadow":
        return "尾盘+漏斗shadow"
    if scope == "tail_buy_only":
        return "尾盘"
    return ""


def policy_next_action_label(raw: Any) -> str:
    text = str(raw or "").strip()
    labels = {
        "manual_review_dynamic_on": "进入人工晋级评审（非正式生效）",
        "run_backtest_confirmation": "先跑回测确认",
        "keep_shadow_backtest_failed": "回测未通过，保持 shadow",
        "keep_static_policy": "保持静态策略",
        "collect_more_shadow_samples": "继续收集样本",
        "keep_shadow_apply_signal_weights": "保持 shadow 并应用信号级调权",
        "keep_shadow_observe": "保持 shadow 观察",
    }
    return labels.get(text, text or "保持观察")


def policy_mode_recommendation_label(raw: Any) -> str:
    text = str(raw or "").strip()
    labels = {
        "review_promote_dynamic_policy": "评审是否切 on",
        "keep_shadow": "保持 shadow",
        "keep_static_policy": "保持静态策略",
    }
    return labels.get(text, text or "保持 shadow")


def policy_execution_mode_label(raw: Any) -> str:
    text = str(raw or "").strip()
    labels = {
        "on": "正式调权(on)",
        "shadow": "shadow 对照(shadow)",
        "off": "静态策略(off)",
        "unknown": "未知模式",
    }
    return labels.get(text, f"{text} 模式" if text else "未知模式")


def policy_promotion_status_label(raw: Any) -> str:
    text = str(raw or "").strip()
    labels = {
        "manual_review_required": "需人工复核",
        "do_not_promote": "禁止晋级",
        "collect_more_samples": "继续收集样本",
        "keep_shadow": "保持 shadow",
    }
    return labels.get(text, text or "未知")


def policy_governor_status_label(raw: Any) -> str:
    text = str(raw or "").strip()
    labels = {
        "candidate": "可进入人工晋级评审",
        "watch": "继续观察",
        "reject": "不建议晋级",
        "insufficient_sample": "样本不足",
    }
    return labels.get(text, text or "未知")


def policy_formal_dynamic_label(execution: dict[str, Any] | None) -> str:
    row = execution or {}
    if row.get("formal_dynamic_allowed") is True:
        return "允许正式生效"
    if row.get("formal_dynamic_allowed") is False:
        reason = str(row.get("formal_dynamic_block_reason") or "").strip()
        return f"未进正式漏斗({reason})" if reason else "未进正式漏斗"
    if str(row.get("next_action") or "").strip() == "manual_review_dynamic_on":
        return "未进正式漏斗(manual_review_required)"
    return "未知"


def policy_governor_display(governor: dict[str, Any] | None) -> dict[str, str]:
    row = governor or {}
    return {
        "status": policy_governor_status_label(row.get("status")),
        "mode_recommendation": policy_mode_recommendation_label(row.get("mode_recommendation")),
        "next_action": policy_next_action_label(row.get("next_action")),
        "promotion_status": policy_promotion_status_label(row.get("promotion_status")),
        "auto_apply": "是" if row.get("auto_apply") else "否",
    }


def policy_execution_display(execution: dict[str, Any] | None) -> dict[str, str]:
    row = execution or {}
    return {
        "active_scope": str(row.get("active_scope") or "无"),
        "promotion_status": policy_promotion_status_label(row.get("promotion_status")),
        "next_action": policy_next_action_label(row.get("next_action")),
        "formal_dynamic": policy_formal_dynamic_label(row),
        "summary": str(row.get("summary") or ""),
    }


def _scope_key(raw: str) -> str:
    key = raw.strip().lower()
    return "entry_type" if key == "entry" else key
