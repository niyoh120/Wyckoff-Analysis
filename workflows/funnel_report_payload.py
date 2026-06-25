"""Structured payloads produced by the funnel run."""

from __future__ import annotations

from typing import Any

from core.candidate_metadata import build_candidate_metadata_map, code6
from core.funnel_report import build_symbol_report_row, candidate_reason_text
from core.market_trade_mode import resolve_market_trade_mode
from workflows.funnel_ai_selection import FunnelAiSelection
from workflows.funnel_settings import FUNNEL_L2_BYPASS_AI_CAP, FUNNEL_STRATEGIC_L2_BYPASS_AI_CAP


def context_regime(ctx: Any) -> str:
    return str(getattr(ctx, "regime", "NEUTRAL") or "NEUTRAL")


def legacy_symbol_rows(ctx: Any, selection: FunnelAiSelection) -> list[dict]:
    metadata_map = _candidate_metadata_map(ctx)
    sos_hit_set = {str(c).strip() for c, _ in ctx.review_triggers.get("sos", [])}
    evr_hit_set = {str(c).strip() for c, _ in ctx.review_triggers.get("evr", [])}
    spring_hit_set = {str(c).strip() for c, _ in ctx.review_triggers.get("spring", [])}
    lps_hit_set = {str(c).strip() for c, _ in ctx.review_triggers.get("lps", [])}

    def infer_track(code: str) -> str:
        if code in ctx.candidate_entry_map:
            track = str(ctx.candidate_entry_map[code].get("track", "")).strip()
            return "Accum" if track == "accumulation" else "Trend"
        if code in sos_hit_set or code in evr_hit_set:
            return "Trend"
        return "Accum" if code in spring_hit_set or code in lps_hit_set else "Trend"

    return [
        _with_candidate_metadata(
            build_symbol_report_row(
                code,
                rank=idx + 1,
                tag=candidate_reason_text(code, ctx.code_to_reasons, ctx.theme_badge_map),
                track=infer_track(code),
                stage=stage_name(ctx, code),
                score=legacy_display_score(ctx, code),
                priority_score=float(ctx.code_to_total_score.get(code, 0.0)),
                selection_source=legacy_selection_source(ctx, code),
                selection_is_fill=False,
                market_regime=context_regime(ctx),
                maps=ctx.report_maps,
            ),
            code,
            metadata_map,
        )
        for idx, code in enumerate(selection.selected_for_ai)
    ]


def modern_symbol_rows(ctx: Any, selection: FunnelAiSelection) -> list[dict]:
    metadata_map = _candidate_metadata_map(ctx)
    return [
        _with_candidate_metadata(
            build_symbol_report_row(
                code,
                rank=idx + 1,
                tag=f"{_source_tag(ctx, code)} | {candidate_reason_text(code, ctx.code_to_reasons, ctx.theme_badge_map)}",
                track=selected_track(selection, code),
                stage=stage_name(ctx, code),
                score=display_score(ctx, selection, code),
                priority_score=float(selection.score_map.get(code, 0.0)),
                selection_source=selection_source(ctx, code),
                selection_is_fill=selection_source(ctx, code) == "l3_fill",
                market_regime=context_regime(ctx),
                maps=ctx.report_maps,
            ),
            code,
            metadata_map,
        )
        for idx, code in enumerate(selection.selected_for_ai)
    ]


def _candidate_metadata_map(ctx: Any) -> dict[str, dict[str, Any]]:
    return build_candidate_metadata_map(
        getattr(ctx, "candidate_entries", []) or [],
        getattr(ctx, "mainline_candidates", []) or [],
    )


def _with_candidate_metadata(row: dict[str, Any], code: str, metadata_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row.update(metadata_map.get(code6(code), {}))
    return row


def _source_tag(ctx: Any, code: str) -> str:
    if code in getattr(ctx, "mainline_candidate_set", set()):
        return "主线买点确认"
    if code in ctx.strategic_l2_bypass_set:
        return "战略L2旁路"
    if code in ctx.l2_bypass_set:
        return "L2旁路观察"
    return str(ctx.l2_channel_map.get(code, "")).strip() or "正式候选"


def funnel_run_details(
    ctx: Any,
    selection: FunnelAiSelection,
    *,
    content: str,
    title: str,
    symbols: list[dict],
) -> dict:
    trade_mode = resolve_market_trade_mode(context_regime(ctx))
    return {
        "metrics": ctx.metrics,
        "trade_mode": {
            "regime": trade_mode.regime,
            "mode": trade_mode.mode,
            "label": trade_mode.label,
            "action": trade_mode.action,
            "reason": trade_mode.reason,
            "allow_ai_review": trade_mode.allow_ai_review,
            "allow_recommendation_write": trade_mode.allow_recommendation_write,
        },
        "triggers": ctx.review_triggers,
        "review_triggers": ctx.review_triggers,
        "formal_triggers": ctx.formal_triggers,
        "l2_bypass_triggers": ctx.bypass_triggers,
        "l2_bypass_selected": [c for c in selection.selected_for_ai if c in ctx.l2_bypass_set],
        "l2_bypass_budget": FUNNEL_L2_BYPASS_AI_CAP,
        "strategic_l2_bypass_triggers": ctx.strategic_l2_bypass_triggers,
        "strategic_l2_bypass_selected": [c for c in selection.selected_for_ai if c in ctx.strategic_l2_bypass_set],
        "strategic_l2_bypass_budget": FUNNEL_STRATEGIC_L2_BYPASS_AI_CAP,
        "mainline_candidates": getattr(ctx, "mainline_candidates", []),
        "mainline_selected": [
            c for c in selection.selected_for_ai if c in getattr(ctx, "mainline_candidate_set", set())
        ],
        "leader_radar_rows": ctx.leader_radar_rows,
        "leader_radar_symbols": sorted(ctx.leader_radar_symbols),
        "candidate_entries": ctx.candidate_entries,
        "external_seed_triggers": ctx.external_seed_triggers,
        "external_seed_selected": [],
        "content": content,
        "title": title,
        "symbols_for_report": symbols,
        "selected_for_ai": selection.selected_for_ai,
        "trend_selected": selection.trend_selected,
        "accum_selected": selection.accum_selected,
        "priority_score_map": selection.score_map,
        "shadow_added": selection.ai_policy.get("shadow_added", []) or [],
        "shadow_removed": selection.ai_policy.get("shadow_removed", []) or [],
        "shadow_score_map": selection.ai_policy.get("shadow_score_map", {}) or {},
        "name_map": ctx.name_map,
        "sector_map": ctx.sector_map,
        "all_df_map": ctx.all_df_map,
    }


def stage_name(ctx: Any, code: str) -> str:
    if code in ctx.candidate_entry_map:
        state = str(ctx.candidate_entry_map[code].get("state", "") or "").strip()
        if state:
            return state
    return "Markup" if code in ctx.markup_symbols else str(ctx.accum_stage_map.get(code, "") or "").strip()


def display_score(ctx: Any, selection: FunnelAiSelection, code: str) -> float:
    trigger_score = float(ctx.code_to_total_score.get(code, 0.0) or 0.0)
    return trigger_score if trigger_score > 0 else float(selection.score_map.get(code, 0.0) or 0.0)


def legacy_display_score(ctx: Any, code: str) -> float:
    fallback = (ctx.metrics.get("layer3_score_map", {}) or {}).get(code, 0.0)
    return float(ctx.code_to_total_score.get(code, 0.0) or fallback)


def legacy_selection_source(ctx: Any, code: str) -> str:
    if code in getattr(ctx, "mainline_candidate_set", set()):
        return "mainline"
    if code in ctx.candidate_entry_map:
        return "alpha_candidate"
    if code in ctx.strategic_l2_bypass_set:
        return "strategic_l2_bypass"
    if code in ctx.l2_bypass_set:
        return "l2_bypass"
    return "l4_hit"


def selection_source(ctx: Any, code: str) -> str:
    if code in getattr(ctx, "mainline_candidate_set", set()):
        return "mainline"
    if code in ctx.candidate_entry_map:
        return "alpha_candidate"
    if code in ctx.strategic_l2_bypass_set:
        return "strategic_l2_bypass"
    if code in ctx.l2_bypass_set:
        return "l2_bypass"
    if code in ctx.formal_hit_set:
        return "l4_hit"
    if code in ctx.markup_symbols:
        return "markup"
    return "accum_c" if stage_name(ctx, code) == "Accum_C" else "l3_fill"


def selected_track(selection: FunnelAiSelection, code: str) -> str:
    if code in selection.trend_selected:
        return "Trend"
    return "Accum" if code in selection.accum_selected else ""
