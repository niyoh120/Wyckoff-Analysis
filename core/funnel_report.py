"""Shared report-row builders for Wyckoff funnel candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.safe import safe_float


@dataclass(frozen=True)
class FunnelReportMaps:
    name_map: dict[str, str]
    sector_map: dict[str, str]
    sector_rotation_map: dict[str, dict]
    exit_signals: dict[str, dict]
    latest_close_map: dict[str, float]
    theme_candidate_map: dict[str, dict]
    theme_bonus_map: dict[str, float]
    code_to_trigger_keys: dict[str, list[str]]
    code_to_reasons: dict[str, list[str]]
    theme_badge_map: dict[str, str]
    capital_migration_bonus_map: dict[str, float] = field(default_factory=dict)
    layer3_score_map: dict[str, float] = field(default_factory=dict)


def build_symbol_report_row(
    code: str,
    *,
    rank: int,
    tag: str,
    track: str,
    stage: str,
    score: float,
    priority_score: float,
    selection_source: str,
    selection_is_fill: bool,
    market_regime: str,
    maps: FunnelReportMaps,
) -> dict[str, Any]:
    row = {
        "code": code,
        "name": maps.name_map.get(code, code),
        "tag": tag.strip(" |"),
        "track": track,
        "stage": stage,
        "score": float(score),
        "priority_score": float(priority_score),
        "priority_rank": rank,
        "selection_source": selection_source,
        "selection_is_fill": bool(selection_is_fill),
        "layer3_quality_score": safe_float(maps.layer3_score_map.get(code)),
        "initial_price": float(maps.latest_close_map.get(code, 0.0) or 0.0),
        "industry": _industry(code, maps.sector_map),
    }
    row.update(signal_report_fields(code, maps.code_to_trigger_keys, track, market_regime, score, selection_source))
    row.update(_sector_fields(row["industry"], maps.sector_rotation_map))
    row.update(_exit_fields(code, maps.exit_signals))
    row.update(theme_report_fields(code, maps.theme_candidate_map, maps.theme_bonus_map))
    row.update(capital_migration_report_fields(code, maps.capital_migration_bonus_map))
    return row


def candidate_reason_text(code: str, code_to_reasons: dict[str, list[str]], badge_map: dict[str, str]) -> str:
    reasons = list(code_to_reasons.get(code, []) or [])
    badge = badge_map.get(code, "")
    if badge and badge not in reasons:
        reasons.append(badge)
    return "、".join(reasons) or "威科夫候选"


def theme_report_fields(code: str, candidate_map: dict[str, dict], bonus_map: dict[str, float]) -> dict[str, Any]:
    item = candidate_map.get(code) or {}
    return {
        "strategic_theme": str(item.get("theme", "") or "").strip(),
        "strategic_theme_score": safe_float(item.get("theme_score")),
        "strategic_stock_score": safe_float(item.get("stock_score")),
        "strategic_theme_state": str(item.get("state", "") or "").strip(),
        "strategic_theme_bonus": safe_float(bonus_map.get(code)),
    }


def capital_migration_report_fields(code: str, bonus_map: dict[str, float]) -> dict[str, float]:
    return {"capital_migration_bonus": safe_float(bonus_map.get(code))}


def signal_report_fields(
    code: str,
    trigger_key_map: dict[str, list[str]],
    track: str,
    regime: str,
    trigger_score: float,
    selection_source: str = "",
) -> dict[str, Any]:
    signal_types = _signal_types(trigger_key_map.get(code, []) or [])
    primary_signal = signal_types[0] if signal_types else _fallback_primary_signal(selection_source, track)
    return {
        "primary_signal": primary_signal,
        "signal_types": signal_types,
        "signal_track": str(track or "").strip(),
        "market_regime": str(regime or "NEUTRAL").strip().upper() or "NEUTRAL",
        "trigger_score": safe_float(trigger_score),
    }


def _fallback_primary_signal(selection_source: str, track: str) -> str:
    """无 L4 trigger key 时，用候选来源代替，避免归因样本里 primary_signal 大面积为空。"""
    source = str(selection_source or "").strip()
    if source:
        return source
    return "strategic_review" if str(track or "").strip() else ""


def _sector_fields(industry: str, sector_rotation_map: dict[str, dict]) -> dict[str, str]:
    row = sector_rotation_map.get(industry, {}) or {}
    return {
        "sector_state_code": str(row.get("state", "")).strip(),
        "sector_state": str(row.get("label", "")).strip(),
        "sector_note": str(row.get("note", "")).strip(),
        "sector_guidance": str(row.get("guidance", "")).strip(),
    }


def _exit_fields(code: str, exit_signals: dict[str, dict]) -> dict[str, Any]:
    row = exit_signals.get(code, {}) or {}
    return {
        "exit_signal": str(row.get("signal", "")).strip(),
        "exit_price": row.get("price"),
        "exit_reason": str(row.get("reason", "")).strip(),
    }


def _signal_types(raw_keys: list[str]) -> list[str]:
    out: list[str] = []
    for key in raw_keys:
        signal = str(key or "").strip()
        if signal and signal not in out:
            out.append(signal)
    return out


def _industry(code: str, sector_map: dict[str, str]) -> str:
    return str(sector_map.get(code, "") or "未知行业")
