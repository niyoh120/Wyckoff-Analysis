"""Preview-only decision-profile reassessment from stock analysis reports."""

from __future__ import annotations

import json
import logging
from typing import Any

from utils.json_text import extract_json_block

logger = logging.getLogger(__name__)


def _reassess_conservative(
    code: str,
    action: str,
    confidence: float,
    entry_low: float | None,
    entry_high: float | None,
    stop_loss: float | None,
    warnings: list[str],
) -> tuple[str, float | None, float | None, float | None]:
    final_action = action
    if confidence < 0.6 and action in ("PROBE", "ATTACK"):
        final_action = "HOLD"
        warnings.append(f"{code} 置信度较低 ({confidence})，动作降级为 HOLD")

    adjusted_low = round(entry_low * 0.98, 2) if entry_low is not None else None
    adjusted_high = round(entry_high * 0.98, 2) if entry_high is not None else None

    adjusted_sl = stop_loss
    if entry_high is not None and stop_loss is not None:
        risk_dist = entry_high - stop_loss
        if risk_dist > 0:
            adjusted_sl = round(entry_high - (risk_dist * 0.85), 2)
    return final_action, adjusted_low, adjusted_high, adjusted_sl


def _reassess_aggressive(
    code: str,
    action: str,
    confidence: float,
    entry_low: float | None,
    entry_high: float | None,
    stop_loss: float | None,
    warnings: list[str],
) -> tuple[str, float | None, float | None, float | None]:
    final_action = action
    if confidence >= 0.7 and action == "HOLD":
        final_action = "PROBE"
        warnings.append(f"{code} 置信度较高 ({confidence})，动作升级为 PROBE")

    adjusted_low = round(entry_low * 1.03, 2) if entry_low is not None else None
    adjusted_high = round(entry_high * 1.03, 2) if entry_high is not None else None

    adjusted_sl = stop_loss
    if entry_high is not None and stop_loss is not None:
        risk_dist = entry_high - stop_loss
        if risk_dist > 0:
            adjusted_sl = round(entry_high - (risk_dist * 1.15), 2)
    return final_action, adjusted_low, adjusted_high, adjusted_sl


def _parse_entry_zone(entry_zone: Any) -> tuple[float | None, float | None]:
    entry_low = None
    entry_high = None
    if isinstance(entry_zone, str) and "-" in entry_zone:
        try:
            parts = entry_zone.split("-")
            entry_low = float(parts[0].strip())
            entry_high = float(parts[1].strip())
        except Exception:
            pass
    elif isinstance(entry_zone, list) and len(entry_zone) == 2:
        try:
            entry_low = float(entry_zone[0])
            entry_high = float(entry_zone[1])
        except Exception:
            pass
    return entry_low, entry_high


def _adjust_decision(
    item: dict,
    profile_norm: str,
    warnings: list[str],
) -> dict[str, Any]:
    code = str(item.get("code", "")).strip()
    name = str(item.get("name", "")).strip()
    action = str(item.get("action", "")).strip().upper()

    entry_zone = item.get("entry_zone", "")
    entry_low, entry_high = _parse_entry_zone(entry_zone)

    try:
        stop_loss = float(item.get("stop_loss")) if item.get("stop_loss") is not None else None
    except Exception:
        stop_loss = None

    try:
        confidence = float(item.get("confidence")) if item.get("confidence") is not None else 1.0
    except Exception:
        confidence = 1.0

    if profile_norm == "conservative":
        final_action, adj_low, adj_high, adj_sl = _reassess_conservative(
            code, action, confidence, entry_low, entry_high, stop_loss, warnings
        )
    elif profile_norm == "aggressive":
        final_action, adj_low, adj_high, adj_sl = _reassess_aggressive(
            code, action, confidence, entry_low, entry_high, stop_loss, warnings
        )
    else:
        final_action, adj_low, adj_high, adj_sl = action, entry_low, entry_high, stop_loss

    return {
        "code": code,
        "name": name,
        "raw_action": action,
        "final_action": final_action,
        "raw_entry_zone": entry_zone,
        "final_entry_zone": f"{adj_low} - {adj_high}" if (adj_low and adj_high) else entry_zone,
        "raw_stop_loss": stop_loss,
        "final_stop_loss": adj_sl,
        "confidence": confidence,
        "reason": item.get("reason", ""),
    }


def reassess_decision_profile(report_text: str, profile: str) -> dict[str, Any]:
    profile_norm = str(profile or "balanced").strip().lower()
    if profile_norm not in ("conservative", "balanced", "aggressive"):
        profile_norm = "balanced"

    try:
        extracted = extract_json_block(report_text)
        data = json.loads(extracted)
        raw_decisions = data.get("decisions", [])
        if raw_decisions is None:
            raw_decisions = []
    except Exception as e:
        logger.debug("Failed to extract JSON block for reassess: %s", e)
        return {"error": f"JSON 解析失败: {e}", "decisions": []}

    if not isinstance(raw_decisions, list):
        return {"error": "decisions 字段不是列表", "decisions": []}

    adjusted_decisions = []
    warnings = []

    for item in raw_decisions:
        if not isinstance(item, dict):
            continue
        if not item.get("code") or not item.get("action"):
            continue
        adjusted_decisions.append(_adjust_decision(item, profile_norm, warnings))

    return {
        "profile": profile_norm,
        "decisions": adjusted_decisions,
        "warnings": warnings,
        "policy_version": "decision-profile-v1",
    }
