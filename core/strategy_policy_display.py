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
        tokens.append(f"active={active}")
    formal_block = str(meta.get("formal_dynamic_block_reason") or "").strip()
    if meta.get("formal_dynamic_allowed") is False and formal_block:
        tokens.append(f"formal_block={formal_block}")
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
        tokens.append(f"report={report_date}")
    if horizon:
        tokens.append(f"h={horizon}")
    age = meta.get("age_days")
    if age is not None and str(age) != "":
        tokens.append(f"age={age}d")
    execution_policy = str(meta.get("execution_policy") or "").strip()
    execution_scope = str(meta.get("execution_scope") or "").strip()
    if execution_policy:
        tokens.append(f"mode={execution_policy}")
    if execution_scope:
        tokens.append(f"scope={execution_scope}")
    next_action = str(meta.get("next_action") or "").strip()
    if next_action:
        tokens.append(f"next={next_action}")
    return tokens


def _policy_active_scope(meta: dict[str, Any]) -> str:
    parts = []
    if meta.get("tail_buy_weights_active") is True:
        parts.append("尾盘")
    if meta.get("funnel_formal_weights_active") is True:
        parts.append("正式漏斗")
    elif meta.get("funnel_shadow_weights_active") is True:
        parts.append("漏斗shadow")
    return "+".join(parts)


def _scope_key(raw: str) -> str:
    key = raw.strip().lower()
    return "entry_type" if key == "entry" else key
