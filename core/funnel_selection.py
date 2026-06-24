"""Candidate merge and promotion rules for the Wyckoff funnel."""

from __future__ import annotations

from core.candidate_ranker import TRIGGER_LABELS
from core.funnel_theme import is_accum_trigger, promotion_limits

DEFENSIVE_QUOTA_REGIMES = {"RISK_OFF", "BEAR_REBOUND", "PANIC_REPAIR", "CRASH", "BLACK_SWAN"}


def merge_trigger_maps(*trigger_maps: dict[str, list[tuple[str, float]]]) -> dict[str, list[tuple[str, float]]]:
    merged: dict[str, list[tuple[str, float]]] = {key: [] for key in TRIGGER_LABELS}
    seen: set[tuple[str, str]] = set()
    for source in trigger_maps:
        _merge_trigger_source(merged, seen, source or {})
    return merged


def split_selected_tracks(
    selected_codes: list[str],
    code_to_trigger_keys: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    trend_selected: list[str] = []
    accum_selected: list[str] = []
    for code in selected_codes:
        if is_accum_trigger(code_to_trigger_keys.get(code, [])):
            accum_selected.append(code)
        else:
            trend_selected.append(code)
    return trend_selected, accum_selected


def rank_l2_bypass_pool(l2_bypass_pool: list[str], code_to_total_score: dict[str, float]) -> list[str]:
    clean_pool = {str(code).strip() for code in l2_bypass_pool if str(code).strip()}
    return sorted(clean_pool, key=lambda c: (-code_to_total_score.get(c, 0.0), c))


def should_force_quota_selection(regime: str, full_mode_enabled: bool, *, defensive_force_quota: bool) -> bool:
    if not full_mode_enabled or not defensive_force_quota:
        return False
    return str(regime or "").strip().upper() in DEFENSIVE_QUOTA_REGIMES


def promote_l2_bypass_for_ai(
    selected_for_ai: list[str],
    trend_selected: list[str],
    accum_selected: list[str],
    l2_bypass_pool: list[str],
    code_to_total_score: dict[str, float],
    code_to_trigger_keys: dict[str, list[str]],
    score_map: dict[str, float],
    *,
    enabled: bool,
    cap: int,
    total_cap: int | None = None,
    accum_codes: set[str] | None = None,
) -> int:
    if not enabled or not l2_bypass_pool:
        return 0
    ranked = rank_l2_bypass_pool(l2_bypass_pool, code_to_total_score)
    item_left, total_left = promotion_limits(selected_for_ai, cap, total_cap)
    return _append_promoted_codes(
        ranked,
        selected_for_ai,
        trend_selected,
        accum_selected,
        code_to_total_score,
        code_to_trigger_keys,
        score_map,
        item_left,
        total_left,
        accum_codes or set(),
    )


def promote_bypass_groups(
    selected_for_ai: list[str],
    trend_selected: list[str],
    accum_selected: list[str],
    pools: dict[str, list[str] | set[str]],
    code_to_total_score: dict[str, float],
    code_to_trigger_keys: dict[str, list[str]],
    score_map: dict[str, float],
    *,
    ai_total_cap: int,
    bypass_enabled: bool,
    bypass_cap: int,
    strategic_enabled: bool,
    strategic_cap: int,
) -> tuple[int, int]:
    bypass_added = promote_l2_bypass_for_ai(
        selected_for_ai,
        trend_selected,
        accum_selected,
        list(pools["l2_bypass"]),
        code_to_total_score,
        code_to_trigger_keys,
        score_map,
        enabled=bypass_enabled,
        cap=bypass_cap,
        total_cap=ai_total_cap,
    )
    strategic_added = promote_l2_bypass_for_ai(
        selected_for_ai,
        trend_selected,
        accum_selected,
        list(pools["strategic_l2_bypass"]),
        code_to_total_score,
        code_to_trigger_keys,
        score_map,
        enabled=strategic_enabled,
        cap=strategic_cap,
        total_cap=ai_total_cap,
        accum_codes=set(pools["strategic_accum"]),
    )
    return bypass_added, strategic_added


def _merge_trigger_source(
    merged: dict[str, list[tuple[str, float]]],
    seen: set[tuple[str, str]],
    source: dict[str, list[tuple[str, float]]],
) -> None:
    for key, hits in source.items():
        bucket = merged.setdefault(str(key), [])
        for code, score in hits or []:
            code_s = str(code).strip()
            dedupe_key = (str(key), code_s)
            if code_s and dedupe_key not in seen:
                bucket.append((code_s, float(score or 0.0)))
                seen.add(dedupe_key)


def _append_promoted_codes(
    ranked: list[str],
    selected_for_ai: list[str],
    trend_selected: list[str],
    accum_selected: list[str],
    code_to_total_score: dict[str, float],
    code_to_trigger_keys: dict[str, list[str]],
    score_map: dict[str, float],
    item_left: int | None,
    total_left: int | None,
    accum_codes: set[str],
) -> int:
    selected_seen = set(selected_for_ai)
    track_seen = set(trend_selected) | set(accum_selected)
    added = 0
    for code in ranked:
        if code not in selected_seen:
            if item_left == 0 or total_left == 0:
                break
            selected_for_ai.append(code)
            selected_seen.add(code)
            added += 1
            item_left = _decrement_optional(item_left)
            total_left = _decrement_optional(total_left)
        score_map.setdefault(code, float(code_to_total_score.get(code, 0.0) or 0.0))
        _append_track_once(code, trend_selected, accum_selected, track_seen, accum_codes, code_to_trigger_keys)
    return added


def _append_track_once(
    code: str,
    trend_selected: list[str],
    accum_selected: list[str],
    track_seen: set[str],
    accum_codes: set[str],
    code_to_trigger_keys: dict[str, list[str]],
) -> None:
    if code in track_seen:
        return
    if code in accum_codes or is_accum_trigger(code_to_trigger_keys.get(code, [])):
        accum_selected.append(code)
    else:
        trend_selected.append(code)
    track_seen.add(code)


def _decrement_optional(value: int | None) -> int | None:
    return None if value is None else value - 1
