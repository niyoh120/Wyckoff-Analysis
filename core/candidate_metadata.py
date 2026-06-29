"""Candidate attribution helpers shared across funnel persistence surfaces."""

from __future__ import annotations

import json
from typing import Any

from core.ai_candidate_allocation import candidate_entry_sort_key
from core.candidate_tracks import candidate_entry_key, normalize_candidate_entry_key

STRATEGY_VERSION_CANDIDATE_LANE_V1 = "candidate_lane_v1"

CANDIDATE_ATTRIBUTION_COLUMNS = (
    "strategy_version",
    "candidate_lane",
    "entry_type",
    "signal_key",
    "candidate_status",
    "candidate_timing",
    "candidate_risk",
    "candidate_reasons",
    "candidate_metrics",
    "mainline_score",
    "theme_score",
    "stock_role_score",
    "quality_score",
    "timing_score",
)


def code6(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def build_candidate_metadata_map(
    candidate_entries: list[dict[str, Any]] | None,
    mainline_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    best_entries: dict[str, dict[str, Any]] = {}
    mainline_by_code = {code6(item.get("code")): item for item in mainline_candidates or [] if code6(item.get("code"))}
    for item in candidate_entries or []:
        code = code6(item.get("code"))
        if not code:
            continue
        current = best_entries.get(code)
        if current is None or _stronger_candidate_entry(item, current):
            best_entries[code] = item
    for code, item in best_entries.items():
        result[code] = candidate_entry_metadata(item, mainline_by_code.get(code))
    for code, item in mainline_by_code.items():
        result.setdefault(code, mainline_metadata(item))
    return result


def candidate_entry_metadata(item: dict[str, Any], mainline: dict[str, Any] | None = None) -> dict[str, Any]:
    lane = _text(item.get("lane")) or _text(item.get("signal_key")) or _text(item.get("entry_type"))
    meta = {
        "strategy_version": STRATEGY_VERSION_CANDIDATE_LANE_V1,
        "candidate_lane": lane,
        "entry_type": _text(item.get("entry_type")) or lane,
        "signal_key": candidate_entry_key(item, fields=("signal_key", "lane", "entry_type"))
        or normalize_signal_key(lane),
        "candidate_status": _text(item.get("state")) or _text((mainline or {}).get("status")),
        "candidate_timing": _text(item.get("timing")) or _text((mainline or {}).get("entry_type")),
        "candidate_risk": _text(item.get("risk")) or _join_texts((mainline or {}).get("risk_flags")),
        "candidate_reasons": _json_object({"reasons": item.get("reasons") or []}),
        "candidate_metrics": _json_object(item.get("metrics") or (mainline or {}).get("metrics") or {}),
    }
    if mainline:
        meta.update(_mainline_score_fields(mainline))
        if meta["candidate_lane"] == "mainline":
            meta["candidate_status"] = _text(mainline.get("status"))
    return _without_empty(meta)


def mainline_metadata(item: dict[str, Any]) -> dict[str, Any]:
    entry_type = _text(item.get("entry_type")) or "mainline"
    meta = {
        "strategy_version": STRATEGY_VERSION_CANDIDATE_LANE_V1,
        "candidate_lane": "mainline",
        "entry_type": entry_type,
        "signal_key": "mainline",
        "candidate_status": _text(item.get("status")),
        "candidate_timing": entry_type,
        "candidate_risk": _join_texts(item.get("risk_flags")),
        "candidate_reasons": _json_object({"reasons": item.get("reasons") or [], "theme": item.get("theme")}),
        "candidate_metrics": _json_object(item.get("metrics") or {}),
        **_mainline_score_fields(item),
    }
    return _without_empty(meta)


def candidate_signal_triggers(candidate_entries: list[dict[str, Any]] | None) -> dict[str, list[tuple[str, float]]]:
    triggers: dict[str, list[tuple[str, float]]] = {}
    best_scores: dict[tuple[str, str], float] = {}
    order: list[tuple[str, str]] = []
    for item in candidate_entries or []:
        code = code6(item.get("code"))
        signal_key = candidate_entry_key(item, fields=("signal_key", "lane", "entry_type"))
        if not code or not signal_key:
            continue
        key = (code, signal_key)
        if key not in best_scores:
            order.append(key)
            best_scores[key] = _score(item)
        else:
            best_scores[key] = max(best_scores[key], _score(item))
    for code, signal_key in order:
        triggers.setdefault(signal_key, []).append((code, best_scores[(code, signal_key)]))
    return triggers


def merge_trigger_maps(*maps: dict[str, list[tuple[str, float]]] | None) -> dict[str, list[tuple[str, float]]]:
    merged: dict[str, list[tuple[str, float]]] = {}
    seen: set[tuple[str, str]] = set()
    for trigger_map in maps:
        for signal_type, hits in (trigger_map or {}).items():
            signal_key = normalize_signal_key(signal_type)
            if not signal_key:
                continue
            for code, score in hits or []:
                code_s = code6(code)
                if not code_s or (code_s, signal_key) in seen:
                    continue
                seen.add((code_s, signal_key))
                merged.setdefault(signal_key, []).append((code_s, _float(score)))
    return merged


def normalize_signal_key(raw: Any) -> str:
    return normalize_candidate_entry_key(raw)


def _stronger_candidate_entry(new_item: dict[str, Any], current: dict[str, Any]) -> bool:
    new_score = _score(new_item)
    current_score = _score(current)
    if new_score != current_score:
        return new_score > current_score
    return candidate_entry_sort_key(new_item) < candidate_entry_sort_key(current)


def _mainline_score_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "mainline_score": _optional_float(item.get("mainline_score")),
        "theme_score": _optional_float(item.get("theme_score")),
        "stock_role_score": _optional_float(item.get("stock_role_score")),
        "quality_score": _optional_float(item.get("quality_score")),
        "timing_score": _optional_float(item.get("timing_score")),
    }


def _score(item: dict[str, Any]) -> float:
    raw = item.get("score")
    if raw is None and item.get("mainline_score") is not None:
        raw = float(item.get("mainline_score") or 0.0) * 100.0
    return _float(raw)


def _float(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value


def _text(raw: Any) -> str | None:
    text = str(raw or "").strip()
    return text or None


def _join_texts(raw: Any) -> str | None:
    if isinstance(raw, list | tuple | set):
        return " / ".join(str(item).strip() for item in raw if str(item).strip()) or None
    return _text(raw)


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if v not in (None, "", [], {})}
    if isinstance(raw, list | tuple | set):
        return {"items": [item for item in raw if item not in (None, "", [], {})]}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"text": raw.strip()}
        return parsed if isinstance(parsed, dict) else {"items": parsed}
    return {}


def _without_empty(meta: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in meta.items() if value not in (None, "", [], {})}
