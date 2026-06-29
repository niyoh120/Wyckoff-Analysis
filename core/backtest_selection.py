"""Candidate selection policy used by historical backtests."""

from __future__ import annotations

import pandas as pd

from core.ai_candidate_allocation import AiCandidateAllocationConfig, allocate_ai_candidates
from core.candidate_policy import (
    CandidatePolicyConfig,
    apply_loss_guard,
    candidate_score_value,
    is_tradeable_l4_trigger_combo,
    loss_guard_reason,
    trigger_sets_by_code,
)
from core.candidate_ranker import rank_l3_candidates
from core.candidate_tracks import (
    best_candidate_entry_map,
    candidate_entry_key,
    candidate_entry_sort_key,
    candidate_entry_track,
)
from core.sector_rotation import analyze_sector_rotation
from core.wyckoff_engine import FunnelConfig, FunnelResult

TRADEABLE_L4_SELECTION_MODES = {"tradeable_l4"}
STRICT_L4_SELECTION_MODES = {"quality_l4", "strict_l4"}
FORMAL_L4_SELECTION_MODES = {"all_formal_l4", "all_l4", "full_formal_l4", "full_l4"}
LEGACY_SELECTION_MODES = {"legacy_full_hits", "legacy_hits", "all_hits", "classic"}
LOSS_GUARD_ENTRY_KEYS = {
    "compression",
    "early_breakout",
    "evr",
    "lps",
    "spring",
    "sos",
    "trend_breakout",
    "trend_lane_pullback",
    "trend_pullback",
    "volatile_pullback",
}


def combine_trigger_scores(triggers: dict[str, list[tuple[str, float]]]) -> dict[str, tuple[float, str]]:
    reason_map: dict[str, list[str]] = {}
    score_map: dict[str, float] = {}
    for key, pairs in triggers.items():
        for code, score in pairs:
            code_s = str(code).strip()
            if not code_s:
                continue
            if code_s not in reason_map:
                reason_map[code_s] = []
            reason_map[code_s].append(key)
            score_map[code_s] = max(candidate_score_value(score_map.get(code_s)), candidate_score_value(score))
    return {code: (score_map.get(code, 0.0), "、".join(reasons)) for code, reasons in reason_map.items()}


def dedup_order(codes: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        code = str(raw).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def track_map_for_hits(codes: list[str], triggers: dict[str, list[tuple[str, float]]]) -> dict[str, str]:
    sos_hit_set = {str(code).strip() for code, _ in triggers.get("sos", [])}
    evr_hit_set = {str(code).strip() for code, _ in triggers.get("evr", [])}
    spring_hit_set = {str(code).strip() for code, _ in triggers.get("spring", [])}
    lps_hit_set = {str(code).strip() for code, _ in triggers.get("lps", [])}
    return {code: _track_for_code(code, sos_hit_set, evr_hit_set, spring_hit_set, lps_hit_set) for code in codes}


def _track_for_code(
    code: str, sos_hit_set: set[str], evr_hit_set: set[str], spring_hit_set: set[str], lps_hit_set: set[str]
) -> str:
    if code in sos_hit_set or code in evr_hit_set:
        return "Trend"
    if code in spring_hit_set or code in lps_hit_set:
        return "Accum"
    return "Trend"


def quota_ai_inputs(
    *,
    result: FunnelResult,
    day_df_map: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    regime: str,
    ai_allocation: AiCandidateAllocationConfig | None = None,
) -> tuple[list[str], list[str], list[str], dict[str, float]]:
    sector_rotation = analyze_sector_rotation(
        day_df_map,
        sector_map,
        universe_symbols=list(day_df_map.keys()),
        focus_sectors=result.top_sectors,
    )
    l3_ranked_symbols, _ = rank_l3_candidates(
        l3_symbols=result.layer3_symbols,
        df_map=day_df_map,
        sector_map=sector_map,
        triggers=result.triggers,
        top_sectors=result.top_sectors,
        l2_channel_map=result.channel_map,
        sector_rotation_map=(sector_rotation or {}).get("state_map", {}) or {},
    )
    trend_sel, accum_sel, score_map = allocate_ai_candidates(
        result,
        l3_ranked_symbols or result.layer3_symbols,
        regime,
        sector_map=sector_map,
        max_per_sector=2,
        allocation_config=ai_allocation,
    )
    return dedup_order(trend_sel + accum_sel), trend_sel, accum_sel, score_map


def select_ai_input_codes(
    *,
    result: FunnelResult,
    day_df_map: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    regime: str,
    selection_mode: str,
    full_formal_l4_max: int = 25,
    candidate_policy: CandidatePolicyConfig | None = None,
    ai_allocation: AiCandidateAllocationConfig | None = None,
) -> tuple[list[str], dict[str, float], dict[str, str]]:
    merged_trigger_map = combine_trigger_scores(result.triggers)
    hit_score_map = {code: candidate_score_value(value[0]) for code, value in merged_trigger_map.items()}
    sorted_hit_codes = sorted(merged_trigger_map.keys(), key=lambda code: -hit_score_map.get(code, 0.0))
    l4_selection = _select_l4_mode_codes(
        result=result,
        sorted_hit_codes=sorted_hit_codes,
        hit_score_map=hit_score_map,
        day_df_map=day_df_map,
        regime=regime,
        selection_mode=selection_mode,
        full_formal_l4_max=full_formal_l4_max,
        candidate_policy=candidate_policy,
    )
    if l4_selection is not None:
        return l4_selection
    return _select_quota_mode(
        result,
        day_df_map,
        sector_map,
        regime,
        selection_mode,
        hit_score_map,
        candidate_policy,
        ai_allocation,
    )


def _select_l4_mode_codes(
    *,
    result: FunnelResult,
    sorted_hit_codes: list[str],
    hit_score_map: dict[str, float],
    day_df_map: dict[str, pd.DataFrame],
    regime: str,
    selection_mode: str,
    full_formal_l4_max: int,
    candidate_policy: CandidatePolicyConfig | None,
) -> tuple[list[str], dict[str, float], dict[str, str]] | None:
    if selection_mode in TRADEABLE_L4_SELECTION_MODES and result.candidate_entries:
        return _select_candidate_entries(result, day_df_map, regime, candidate_policy)
    if selection_mode in STRICT_L4_SELECTION_MODES or selection_mode in TRADEABLE_L4_SELECTION_MODES:
        trigger_sets = trigger_sets_by_code(result.triggers)
        selected_codes = [
            code for code in sorted_hit_codes if is_tradeable_l4_trigger_combo(trigger_sets.get(code, set()))
        ]
    elif selection_mode in FORMAL_L4_SELECTION_MODES or selection_mode in LEGACY_SELECTION_MODES:
        selected_codes = sorted_hit_codes if full_formal_l4_max <= 0 else sorted_hit_codes[:full_formal_l4_max]
    else:
        return None
    score_map = {code: hit_score_map.get(code, 0.0) for code in selected_codes}
    track_map = track_map_for_hits(selected_codes, result.triggers)
    if selection_mode in TRADEABLE_L4_SELECTION_MODES:
        selected_codes = _apply_tradeable_loss_guard(
            selected_codes, track_map, result, day_df_map, regime, hit_score_map, candidate_policy
        )
        score_map = {code: score_map.get(code, 0.0) for code in selected_codes}
        track_map = {code: track_map[code] for code in selected_codes}
    return selected_codes, score_map, track_map


def _apply_tradeable_loss_guard(
    selected_codes: list[str],
    track_map: dict[str, str],
    result: FunnelResult,
    day_df_map: dict[str, pd.DataFrame],
    regime: str,
    hit_score_map: dict[str, float],
    candidate_policy: CandidatePolicyConfig | None,
) -> list[str]:
    trend_sel = [code for code in selected_codes if track_map.get(code) == "Trend"]
    accum_sel = [code for code in selected_codes if track_map.get(code) == "Accum"]
    kept, _trend_kept, _accum_kept, _ = apply_loss_guard(
        selected_codes,
        trend_sel,
        accum_sel,
        regime=regime,
        code_to_trigger_keys=trigger_sets_by_code(result.triggers),
        code_to_total_score=hit_score_map,
        channel_map=result.channel_map,
        df_map=day_df_map,
        config=candidate_policy,
    )
    return kept


def _select_candidate_entries(
    result: FunnelResult,
    day_df_map: dict[str, pd.DataFrame],
    regime: str,
    candidate_policy: CandidatePolicyConfig | None,
) -> tuple[list[str], dict[str, float], dict[str, str]]:
    best_entries = best_candidate_entry_map(
        [
            item
            for item in result.candidate_entries or []
            if not candidate_entry_loss_guard(
                item,
                result=result,
                day_df_map=day_df_map,
                regime=regime,
                candidate_policy=candidate_policy,
            )
        ],
    )
    entries = sorted(
        best_entries.values(),
        key=candidate_entry_sort_key,
    )
    selected_codes = dedup_order([str(item.get("code", "")).strip() for item in entries])
    score_map, track_map = _candidate_entry_maps(entries)
    return selected_codes, score_map, track_map


def _candidate_entry_maps(entries: list[dict[str, object]]) -> tuple[dict[str, float], dict[str, str]]:
    score_map: dict[str, float] = {}
    track_map: dict[str, str] = {}
    for item in entries:
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        score = candidate_score_value(item.get("score"))
        if code not in score_map or score > score_map[code]:
            score_map[code] = score
            track_map[code] = _candidate_entry_track(item)
    return score_map, track_map


def _candidate_entry_track(item: dict[str, object]) -> str:
    return candidate_entry_track(item)


def candidate_entry_loss_guard(
    item: dict[str, object],
    *,
    result: FunnelResult,
    day_df_map: dict[str, pd.DataFrame],
    regime: str,
    candidate_policy: CandidatePolicyConfig | None = None,
) -> str:
    code = str(item.get("code", "")).strip()
    if not code:
        return "empty_code"
    entry_type = candidate_entry_key(item, LOSS_GUARD_ENTRY_KEYS)
    return loss_guard_reason(
        code,
        regime,
        [entry_type],
        candidate_score_value(item.get("score")),
        str(result.channel_map.get(code, "") or ""),
        day_df_map,
        config=candidate_policy,
    )


def _select_quota_mode(
    result: FunnelResult,
    day_df_map: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    regime: str,
    selection_mode: str,
    hit_score_map: dict[str, float],
    candidate_policy: CandidatePolicyConfig | None,
    ai_allocation: AiCandidateAllocationConfig | None,
) -> tuple[list[str], dict[str, float], dict[str, str]]:
    selected_codes, trend_sel, accum_sel, score_map = quota_ai_inputs(
        result=result,
        day_df_map=day_df_map,
        sector_map=sector_map,
        regime=regime,
        ai_allocation=ai_allocation,
    )
    if selection_mode in TRADEABLE_L4_SELECTION_MODES:
        selected_codes, trend_sel, accum_sel, _ = apply_loss_guard(
            selected_codes,
            trend_sel,
            accum_sel,
            regime=regime,
            code_to_trigger_keys=trigger_sets_by_code(result.triggers),
            code_to_total_score=hit_score_map,
            channel_map=result.channel_map,
            df_map=day_df_map,
            config=candidate_policy,
        )
    selected_codes = _apply_min_score(selected_codes, score_map)
    track_map = dict.fromkeys(trend_sel, "Trend")
    track_map.update(dict.fromkeys(accum_sel, "Accum"))
    return selected_codes, score_map, track_map


def _apply_min_score(selected_codes: list[str], score_map: dict[str, float]) -> list[str]:
    min_score = float(getattr(FunnelConfig, "min_funnel_score", 0.15) or 0)
    if min_score > 0 and score_map:
        return [code for code in selected_codes if candidate_score_value(score_map.get(code)) >= min_score]
    return selected_codes
