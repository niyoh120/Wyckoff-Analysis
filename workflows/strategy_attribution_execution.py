"""Execution-state helpers for strategy attribution policy outputs."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from core.strategy_policy_display import format_policy_signal_label, safe_policy_weight

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
    action_count = len(action_details)
    if action_count <= 0:
        scope = "none"
        summary = "暂无可执行信号调权。"
    elif mode == "on":
        scope = "tail_buy_and_funnel"
        summary = f"h={horizon} 信号级调权会影响尾盘策略和漏斗正式候选。"
    elif mode == "shadow":
        scope = "tail_buy_and_funnel_shadow"
        summary = f"h={horizon} 信号级调权会影响尾盘策略，并用于漏斗动态策略 shadow 对照。"
    else:
        scope = "tail_buy_only"
        summary = f"h={horizon} 信号级调权会影响尾盘策略；漏斗动态策略当前关闭。"
    return {
        "funnel_dynamic_policy": mode,
        "horizon": horizon,
        "tail_buy_reads_attribution": action_count > 0,
        "signal_action_count": action_count,
        "action_details": action_details,
        "scope": scope,
        "summary": _auto_apply_note(summary, governor),
    }


def funnel_dynamic_policy_mode(*, workflow_path: Path | None = None) -> str:
    raw = os.getenv("FUNNEL_DYNAMIC_POLICY")
    if raw is not None:
        return _normalize_mode(raw)
    path = workflow_path or DEFAULT_FUNNEL_WORKFLOW_PATH
    return _workflow_default_mode(path) or "off"


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


def _action_detail(item: dict[str, Any], action: str) -> dict[str, Any]:
    payload = _json_payload(item.get("reason"))
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    target = str(item.get("target") or payload.get("target") or "").strip()
    return {
        "action": action,
        "horizon": _horizon_from_item(item),
        "target": target,
        "label": format_policy_signal_label(target, scope),
        "weight_multiplier": safe_policy_weight(payload.get("weight_multiplier")),
        "scope": scope,
        "evidence": payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
    }


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
    if governor.get("auto_apply"):
        return summary
    return summary + " 策略治理器不会自动把 FUNNEL_DYNAMIC_POLICY 晋级到 on。"
