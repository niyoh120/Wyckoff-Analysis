"""Funnel card rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from core.candidate_ranker import TRIGGER_GROUP_ORDER, TRIGGER_GROUP_TITLES, TRIGGER_LABELS, TRIGGER_SHORT_LABELS
from core.funnel_etf import append_etf_section
from core.funnel_sections import append_formal_l4_sections, append_leader_radar_section, score_star
from core.theme_radar import summarize_theme_radar
from workflows.funnel_ai_selection import FunnelAiSelection
from workflows.funnel_report_payload import (
    display_score,
    funnel_run_details,
    legacy_symbol_rows,
    modern_symbol_rows,
    stage_name,
)
from workflows.funnel_settings import (
    FUNNEL_BYPASS_DISPLAY_LIMIT,
    FUNNEL_ETF_DISPLAY_LIMIT,
    FUNNEL_L2_BYPASS_AI_CAP,
    FUNNEL_LEADER_RADAR_DISPLAY_LIMIT,
)


@dataclass(frozen=True)
class FunnelRenderedCard:
    title: str
    content: str
    symbols: list[dict]
    benchmark_context: dict
    details: dict | None = None


def render_modern_funnel_card(
    ctx: Any,
    selection: FunnelAiSelection,
    *,
    return_details: bool,
) -> FunnelRenderedCard:
    content = "\n".join(_build_modern_card_lines(ctx, selection))
    title = _funnel_card_title()
    symbols = modern_symbol_rows(ctx, selection)
    details = None
    if return_details:
        details = funnel_run_details(ctx, selection, content=content, title=title, symbols=symbols)
    return FunnelRenderedCard(title, content, symbols, ctx.benchmark_context, details)


def render_legacy_funnel_card(
    ctx: Any,
    selection: FunnelAiSelection,
    *,
    return_details: bool,
) -> FunnelRenderedCard:
    content = "\n".join(_build_legacy_card_lines(ctx, selection))
    title = _funnel_card_title()
    symbols = legacy_symbol_rows(ctx, selection)
    details = None
    if return_details:
        legacy_details_selection = FunnelAiSelection(
            selected_for_ai=selection.selected_for_ai,
            trend_selected=[],
            accum_selected=[],
            score_map=selection.score_map,
            ai_policy=selection.ai_policy,
            theme_promoted_count=selection.theme_promoted_count,
        )
        details = funnel_run_details(ctx, legacy_details_selection, content=content, title=title, symbols=symbols)
    return FunnelRenderedCard(title, content, symbols, ctx.benchmark_context, details)


def _money_flow_report_line(benchmark_context: dict | None) -> str:
    if not benchmark_context:
        return "暂无资金趋势"
    money_flow = benchmark_context.get("money_flow") or {}
    summary = str(money_flow.get("summary") or "").strip()
    if summary:
        return summary
    state = str(money_flow.get("state") or "未知").strip()
    score = money_flow.get("score")
    sample = int(money_flow.get("sample_size") or 0)
    return f"{state}，资金分 {score}，样本 {sample} 只。"


def _amount_distribution_report_line(benchmark_context: dict | None) -> str:
    if not benchmark_context:
        return "暂无成交额分布"
    amount_distribution = benchmark_context.get("amount_distribution") or {}
    summary = str(amount_distribution.get("summary") or "").strip()
    if summary:
        return summary
    state = str(amount_distribution.get("state") or "unknown").strip()
    sample = int(amount_distribution.get("sample_size") or 0)
    return f"成交额分布：{state}，样本 {sample} 只。"


def _pv_policy_shadow_report_line(benchmark_context: dict | None) -> str:
    if not benchmark_context:
        return ""
    shadow = benchmark_context.get("market_pv_policy_shadow") or {}
    if not shadow:
        return ""
    bias = str(shadow.get("risk_bias") or "neutral")
    cfg_overrides = shadow.get("funnel_config_overrides") or {}
    candidate_overrides = shadow.get("candidate_policy_overrides") or {}
    return f"{bias} | Funnel={cfg_overrides or '无'} | AI={candidate_overrides or '无'}"


def _market_report_lines(benchmark_context: dict | None) -> tuple[str, str, str, str, str]:
    bench_line = "未知"
    pv_line = "暂无大盘量价推演"
    money_line = _money_flow_report_line(benchmark_context)
    amount_line = _amount_distribution_report_line(benchmark_context)
    pv_shadow_line = _pv_policy_shadow_report_line(benchmark_context)
    if not benchmark_context:
        return bench_line, money_line, amount_line, pv_line, pv_shadow_line
    close = float(benchmark_context.get("close") or 0)
    ma50 = float(benchmark_context.get("ma50") or 0)
    ma200 = float(benchmark_context.get("ma200") or 0)
    cum3 = float(benchmark_context.get("recent3_cum_pct") or 0)
    bench_line = (
        f"{benchmark_context.get('regime')} | 收盘 {close:.2f} | MA50 {ma50:.2f} | "
        f"MA200 {ma200:.2f} | 近3日 {cum3:+.2f}%"
    )
    pv_line = str(benchmark_context.get("market_pv_outlook") or benchmark_context.get("market_pv_summary") or pv_line)
    return bench_line, money_line, amount_line, pv_line, pv_shadow_line


def _funnel_card_title() -> str:
    return f"🔬 Wyckoff Funnel {date.today().strftime('%Y-%m-%d')}"


def _trigger_short_reasons(code: str, triggers: dict[str, list[tuple[str, float]]]) -> list[str]:
    reasons: list[str] = []
    for key in TRIGGER_LABELS:
        for hit_code, _ in triggers.get(key, []):
            if hit_code == code:
                reasons.append(TRIGGER_SHORT_LABELS.get(key, key))
    return reasons


def _append_l2_bypass_card_section(lines: list[str], ctx: Any, selected_count: int) -> None:
    if not ctx.l2_bypass_pool:
        return
    lines.append("")
    lines.append(f"**【👁 L2旁路观察】{len(ctx.l2_bypass_pool)} 只**")
    lines.append(f"未过L2强度，按形态分数排序；送AI复核 {selected_count} 只")
    display_pool = (
        ctx.l2_bypass_ranked if FUNNEL_BYPASS_DISPLAY_LIMIT <= 0 else ctx.l2_bypass_ranked[:FUNNEL_BYPASS_DISPLAY_LIMIT]
    )
    for code in display_pool:
        name = ctx.name_map.get(code, code)
        reasons = "+".join(_trigger_short_reasons(code, ctx.bypass_triggers))
        industry = str(ctx.sector_map.get(code, "") or "")
        theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
        lines.append(f"  {code} {name}  {reasons}  [{industry}]{theme_badge}")
    omitted = len(ctx.l2_bypass_pool) - len(display_pool)
    if omitted > 0:
        lines.append(f"  ... 另 {omitted} 只略")


def _append_strategic_bypass_card_section(lines: list[str], ctx: Any, selected_count: int) -> None:
    if not ctx.strategic_l2_bypass_pool:
        return
    lines.append("")
    lines.append(f"**【🧭 战略L2旁路】{len(ctx.strategic_l2_bypass_pool)} 只**")
    lines.append(f"L1通过但L2未过，需同时满足战略观察池与L4/阶段复核；送AI复核 {selected_count} 只")
    display_pool = (
        ctx.strategic_l2_bypass_ranked
        if FUNNEL_BYPASS_DISPLAY_LIMIT <= 0
        else ctx.strategic_l2_bypass_ranked[:FUNNEL_BYPASS_DISPLAY_LIMIT]
    )
    for code in display_pool:
        name = ctx.name_map.get(code, code)
        short = "+".join(TRIGGER_SHORT_LABELS.get(k, k) for k in ctx.code_to_trigger_keys.get(code, []))
        stage = str(ctx.strategic_l2_bypass_stage_map.get(code, "") or "").strip()
        reason = " / ".join(x for x in [short, stage] if x) or "战略复核"
        theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
        lines.append(f"  {code} {name}  {reason}{theme_badge}")
    omitted = len(ctx.strategic_l2_bypass_pool) - len(display_pool)
    if omitted > 0:
        lines.append(f"  ... 另 {omitted} 只略")


def _append_legacy_selected_sections(lines: list[str], ctx: Any, selected_for_ai: list[str]) -> None:
    multi_signal = [
        c
        for c in selected_for_ai
        if c not in ctx.strategic_l2_bypass_set and len(ctx.code_to_trigger_keys.get(c, [])) > 1
    ]
    if multi_signal:
        lines.append(f"**【🔥 多信号共振】{len(multi_signal)} 只**")
        for code in sorted(multi_signal, key=lambda c: -ctx.code_to_total_score.get(c, 0)):
            name = ctx.name_map.get(code, code)
            short = "+".join(TRIGGER_SHORT_LABELS.get(k, k) for k in ctx.code_to_trigger_keys.get(code, []))
            score = ctx.code_to_total_score.get(code, 0)
            theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
            lines.append(f"{score_star(score)} {code} {name}  {score:.2f}  {short}{theme_badge}")
        lines.append("")
    single_signal_codes = [
        c for c in selected_for_ai if c not in set(multi_signal) and c not in ctx.strategic_l2_bypass_set
    ]
    code_primary_key = {code: (ctx.code_to_trigger_keys.get(code, []) or ["sos"])[0] for code in single_signal_codes}
    for group_key in TRIGGER_GROUP_ORDER:
        group_codes = [c for c in single_signal_codes if code_primary_key.get(c) == group_key]
        if not group_codes:
            continue
        lines.append(f"**【{TRIGGER_GROUP_TITLES.get(group_key, group_key)}】{len(group_codes)} 只**")
        for code in sorted(group_codes, key=lambda c: -ctx.code_to_total_score.get(c, 0)):
            name = ctx.name_map.get(code, code)
            score = ctx.code_to_total_score.get(code, 0)
            theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
            lines.append(f"{score_star(score)} {code} {name}  {score:.2f}{theme_badge}")
        lines.append("")


def _build_legacy_card_lines(ctx: Any, selection: FunnelAiSelection) -> list[str]:
    bench_line, money_line, amount_line, pv_line, pv_shadow_line = _market_report_lines(ctx.benchmark_context)
    selected_for_ai = selection.selected_for_ai
    lines = [
        (
            f"**股票池**: 主板{ctx.metrics['pool_main']} + 创业板{ctx.metrics['pool_chinext']} "
            f"+ 科创板{ctx.metrics['pool_star']} -> 去重{ctx.metrics['pool_merged']} "
            f"-> 去ST{ctx.metrics['pool_st_excluded']} = {ctx.metrics['total_symbols']} "
            f"(共{ctx.metrics['pool_batches']}批)"
        ),
        f"**漏斗概览**: {ctx.metrics['total_symbols']}只 → L1:{ctx.metrics['layer1']} → L2:{ctx.metrics['layer2']} → L3:{ctx.metrics['layer3']} → 命中:{ctx.metrics['total_hits']}",
        f"**大盘水温**: {bench_line}",
        f"**大盘资金趋势**: {money_line}",
        f"**成交额分布**: {amount_line}",
        f"**大盘量价推演**: {pv_line}",
        f"**推演策略 Shadow**: {pv_shadow_line or '无'}",
        f"**中长线主线**: {summarize_theme_radar(ctx.metrics.get('theme_radar') or {})} ({ctx.theme_radar_source})",
        f"**龙头雷达**: {len(ctx.leader_radar_rows)}只（观察池，非买点/非订单）",
        f"**潜在大涨候选板**: {len(ctx.candidate_entries)}只 / 类型 {ctx.metrics.get('candidate_entry_types', {}) or {}}",
        (
            f"**战略主线联动**: 观察池{len(ctx.theme_candidate_map)}只 / 正式L4命中{ctx.theme_l4_count}只 / "
            f"战略L2旁路{len(ctx.strategic_l2_bypass_pool)}只 / 加权送审{selection.theme_promoted_count}只"
        ),
        f"**候选分层**: 正式L4命中{ctx.unique_hit_count}只 / L2明珠池{len(ctx.l2_bypass_pool)}只 "
        f"-> AI输入{len(selected_for_ai)}只 "
        f"(正式L4 {sum(1 for c in selected_for_ai if c in ctx.formal_hit_set)} / "
        f"L2明珠 {sum(1 for c in selected_for_ai if c in ctx.l2_bypass_set)} / "
        f"战略旁路 {sum(1 for c in selected_for_ai if c in ctx.strategic_l2_bypass_set)}; "
        f"旁路预算 {FUNNEL_L2_BYPASS_AI_CAP or 'unlimited'})",
        f"**Top 行业**: {', '.join(ctx.metrics['top_sectors']) if ctx.metrics['top_sectors'] else '无'}",
        "",
    ]
    if ctx.external_seed_line:
        lines.insert(-1, f"**外部观察 Shadow**: {ctx.external_seed_line}")
    append_etf_section(lines, ctx.etf_metrics, ctx.etf_candidates, display_limit=FUNNEL_ETF_DISPLAY_LIMIT)
    if ctx.etf_metrics or ctx.etf_candidates:
        lines.append("")
    append_leader_radar_section(
        lines, ctx.leader_radar_rows, ctx.name_map, display_limit=FUNNEL_LEADER_RADAR_DISPLAY_LIMIT
    )
    _append_legacy_selected_sections(lines, ctx, selected_for_ai)
    if not selected_for_ai:
        lines.append("无")
    _append_l2_bypass_card_section(lines, ctx, sum(1 for c in selected_for_ai if c in ctx.l2_bypass_set))
    _append_strategic_bypass_card_section(
        lines, ctx, sum(1 for c in selected_for_ai if c in ctx.strategic_l2_bypass_set)
    )
    return lines


def _modern_selection_counts(ctx: Any, selection: FunnelAiSelection) -> dict[str, int]:
    selected = selection.selected_for_ai
    hit_selected = sum(1 for c in selected if c in ctx.formal_hit_set)
    bypass_selected = sum(1 for c in selected if c in ctx.l2_bypass_set)
    strategic_selected = sum(1 for c in selected if c in ctx.strategic_l2_bypass_set)
    return {
        "formal_event": sum(len(v) for v in ctx.formal_triggers.values()),
        "hit_selected": hit_selected,
        "bypass_selected": bypass_selected,
        "strategic_selected": strategic_selected,
        "l3_only": max(len(selected) - hit_selected - bypass_selected - strategic_selected, 0),
    }


def _print_modern_selection_summary(ctx: Any, selection: FunnelAiSelection, counts: dict[str, int]) -> None:
    policy = selection.ai_policy
    print(
        f"[funnel] 候选分层: 正式L4事件={counts['formal_event']}, 正式命中股票={ctx.unique_hit_count}, "
        f"L2明珠池={len(ctx.l2_bypass_pool)}, review候选={ctx.review_unique_count}, "
        f"配额配置=[{ctx.regime}->{policy['quota_family']}: requested Trend={policy['requested_trend_quota']}, "
        f"requested Accum={policy['requested_accum_quota']}, effective Trend={policy['trend_quota']}, "
        f"effective Accum={policy['accum_quota']}, 总上限={policy['total_cap']}, "
        f"l3_fill_limit Trend={policy['max_trend_l3_fill']}, Accum={policy['max_accum_l3_fill']}], "
        f"最终选入: Trend={len(selection.trend_selected)}, Accum={len(selection.accum_selected)}, "
        f"战略旁路={counts['strategic_selected']}, 总计={len(selection.selected_for_ai)}"
    )


def _modern_header_lines(ctx: Any, selection: FunnelAiSelection, counts: dict[str, int]) -> list[str]:
    bench_line, money_line, amount_line, pv_line, pv_shadow_line = _market_report_lines(ctx.benchmark_context)
    policy = selection.ai_policy
    lines = [
        (
            f"**股票池**: 主板{ctx.metrics['pool_main']} + 创业板{ctx.metrics['pool_chinext']} "
            f"+ 科创板{ctx.metrics['pool_star']} -> 去重{ctx.metrics['pool_merged']} "
            f"-> 去ST{ctx.metrics['pool_st_excluded']} = {ctx.metrics['total_symbols']} "
            f"(共{ctx.metrics['pool_batches']}批)"
        ),
        f"**漏斗概览**: {ctx.metrics['total_symbols']}只 → L1:{ctx.metrics['layer1']} → L2:{ctx.metrics['layer2']} → L3:{ctx.metrics['layer3']} → 正式L4:{ctx.unique_hit_count}",
        f"**大盘水温**: {bench_line}",
        f"**大盘资金趋势**: {money_line}",
        f"**成交额分布**: {amount_line}",
        f"**大盘量价推演**: {pv_line}",
        f"**推演策略 Shadow**: {pv_shadow_line or '无'}",
        f"**中长线主线**: {summarize_theme_radar(ctx.metrics.get('theme_radar') or {})} ({ctx.theme_radar_source})",
        f"**龙头雷达**: {len(ctx.leader_radar_rows)}只（观察池，非买点/非订单）",
        f"**潜在大涨候选板**: {len(ctx.candidate_entries)}只 / 类型 {ctx.metrics.get('candidate_entry_types', {}) or {}}",
        (
            f"**战略主线联动**: 观察池{len(ctx.theme_candidate_map)}只 / 正式L4命中{ctx.theme_l4_count}只 / "
            f"战略L2旁路{len(ctx.strategic_l2_bypass_pool)}只 / 加权送审{selection.theme_promoted_count}只"
        ),
        f"**候选分层**: 正式L4命中{ctx.unique_hit_count}只 / L2明珠池{len(ctx.l2_bypass_pool)}只 "
        f"-> AI输入{len(selection.selected_for_ai)}只 "
        f"(配额 {policy['quota_family']}: Trend {len(selection.trend_selected)}/{policy['trend_quota']}, "
        f"Accum {len(selection.accum_selected)}/{policy['accum_quota']}; 正式L4 {counts['hit_selected']} / "
        f"L3补充{counts['l3_only']} / L2明珠 {counts['bypass_selected']} / "
        f"战略旁路 {counts['strategic_selected']}; 旁路预算 {FUNNEL_L2_BYPASS_AI_CAP or 'unlimited'})",
        f"**Top 行业**: {', '.join(ctx.metrics['top_sectors']) if ctx.metrics['top_sectors'] else '无'}",
        "",
    ]
    if ctx.external_seed_line:
        lines.insert(-1, f"**外部观察 Shadow**: {ctx.external_seed_line}")
    if policy.get("shadow_table"):
        lines.insert(
            -1,
            f"**动态策略 Shadow**: `{policy['shadow_table']}` 写入{policy.get('shadow_written', 0)}行；"
            f"shadow新增{policy.get('shadow_added_count', 0)}只，移除{policy.get('shadow_removed_count', 0)}只",
        )
    return lines


def _append_modern_fill_section(lines: list[str], ctx: Any, selection: FunnelAiSelection) -> None:
    fill_codes = [
        c
        for c in selection.selected_for_ai
        if c not in ctx.formal_hit_set and c not in ctx.l2_bypass_set and c not in ctx.strategic_l2_bypass_set
    ]
    if not fill_codes:
        return
    lines.append(f"**【🧭 L3/阶段补位】{len(fill_codes)} 只**")
    for code in sorted(fill_codes, key=lambda c: -display_score(ctx, selection, c)):
        name = ctx.name_map.get(code, code)
        stage = stage_name(ctx, code)
        channel = str(ctx.l2_channel_map.get(code, "")).strip()
        suffix = " / ".join(x for x in [stage, channel] if x)
        score = display_score(ctx, selection, code)
        theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
        lines.append(
            f"{score_star(score)} {code} {name}  {score:.2f}" + (f"  {suffix}" if suffix else "") + theme_badge
        )
    lines.append("")


def _append_modern_strategic_bypass_section(lines: list[str], ctx: Any, selected_count: int) -> None:
    if not ctx.strategic_l2_bypass_pool:
        return
    lines.append("")
    lines.append(f"**【🧭 战略L2旁路】{len(ctx.strategic_l2_bypass_pool)} 只**")
    lines.append(f"L1通过但L2未过，需同时满足战略观察池与L4/阶段复核；送AI复核 {selected_count} 只")
    display_pool = (
        ctx.strategic_l2_bypass_ranked
        if FUNNEL_BYPASS_DISPLAY_LIMIT <= 0
        else ctx.strategic_l2_bypass_ranked[:FUNNEL_BYPASS_DISPLAY_LIMIT]
    )
    for code in display_pool:
        name = ctx.name_map.get(code, code)
        reasons = "+".join(_trigger_short_reasons(code, ctx.strategic_l2_bypass_triggers))
        stage = str(ctx.strategic_l2_bypass_stage_map.get(code, "") or "").strip()
        reason = " / ".join(x for x in [reasons, stage] if x) or "战略复核"
        theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
        lines.append(f"  {code} {name}  {reason}{theme_badge}")
    omitted = len(ctx.strategic_l2_bypass_pool) - len(display_pool)
    if omitted > 0:
        lines.append(f"  ... 另 {omitted} 只略")


def _build_modern_card_lines(ctx: Any, selection: FunnelAiSelection) -> list[str]:
    counts = _modern_selection_counts(ctx, selection)
    _print_modern_selection_summary(ctx, selection, counts)
    lines = _modern_header_lines(ctx, selection, counts)
    append_etf_section(lines, ctx.etf_metrics, ctx.etf_candidates, display_limit=FUNNEL_ETF_DISPLAY_LIMIT)
    if ctx.etf_metrics or ctx.etf_candidates:
        lines.append("")
    append_leader_radar_section(
        lines, ctx.leader_radar_rows, ctx.name_map, display_limit=FUNNEL_LEADER_RADAR_DISPLAY_LIMIT
    )
    if ctx.formal_sorted_codes:
        lines.append("**正式L4展开**: 以下列出全部正式L4；标记 →AI 的进入 Step3 研报")
        append_formal_l4_sections(
            lines,
            ctx.formal_sorted_codes,
            selection.selected_for_ai,
            ctx.name_map,
            ctx.code_to_trigger_keys,
            lambda code: display_score(ctx, selection, code),
            ctx.theme_badge_map,
        )
    _append_modern_fill_section(lines, ctx, selection)
    if not selection.selected_for_ai:
        lines.append("无")
    _append_l2_bypass_card_section(lines, ctx, counts["bypass_selected"])
    _append_modern_strategic_bypass_section(lines, ctx, counts["strategic_selected"])
    return lines
