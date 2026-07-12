"""Funnel card rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from core.candidate_ranker import TRIGGER_GROUP_ORDER, TRIGGER_GROUP_TITLES, TRIGGER_LABELS, TRIGGER_SHORT_LABELS
from core.candidate_tracks import candidate_entry_key
from core.execution_playbook import funnel_playbook_lines
from core.funnel_etf import append_etf_section
from core.funnel_sections import append_formal_l4_sections, score_star
from core.market_trade_mode import resolve_market_trade_mode
from core.signal_confirmation import score_springboard_abc
from core.strategy_policy_display import format_policy_meta_text, format_policy_weight_text
from core.theme_radar import summarize_theme_radar
from workflows.funnel_ai_selection import FunnelAiSelection
from workflows.funnel_report_payload import (
    display_score,
    funnel_run_details,
    legacy_symbol_rows,
    modern_symbol_rows,
    selected_track,
    stage_name,
)
from workflows.funnel_settings import (
    FUNNEL_BYPASS_DISPLAY_LIMIT,
    FUNNEL_ETF_DISPLAY_LIMIT,
    FUNNEL_L2_BYPASS_AI_CAP,
    FUNNEL_MAINLINE_DISPLAY_LIMIT,
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


def _capital_migration_report_lines(metrics: dict | None) -> list[str]:
    migration = (metrics or {}).get("capital_migration") or {}
    if not migration:
        return []
    summary = str(migration.get("summary") or "暂无明确资金迁徙信号").strip()
    confidence = str(migration.get("confidence") or "low").strip()
    lines = [f"**资金迁徙雷达**: {summary} | 置信度 {confidence}"]
    for item in (migration.get("rotation") or [])[:2]:
        text = str(item or "").strip()
        if text:
            lines.append(f"  - {text}")
    activity = _capital_migration_activity_line(migration)
    if activity:
        lines.append(f"  - {activity}")
    return lines


def _capital_migration_activity_line(migration: dict) -> str:
    rows = list(migration.get("activity") or [])[:5]
    if not rows:
        return ""
    return "异动: " + "； ".join(f"{row['theme']}({row['evidence']})" for row in rows)


def _theme_activity_report_line(metrics: dict | None) -> str:
    text = str((metrics or {}).get("theme_activity_summary") or "").strip()
    return f"**今日异动主题**: {text}" if text else ""


def _hot_events_report_line(metrics: dict | None) -> str:
    text = str((metrics or {}).get("ths_hot_events_summary") or "").strip()
    return f"**今日事件主线**: {text}" if text else ""


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


def _trade_mode_report_line(regime: str) -> str:
    mode = resolve_market_trade_mode(regime)
    return f"{mode.label} | {mode.action} | {mode.reason}"


def _execution_decision_line(regime: str, selected_count: int, data_quality: dict | None = None) -> str:
    if (data_quality or {}).get("trade_readiness") == "observe_only":
        return "数据质量降级；候选仅供 shadow 观察，禁止正式推荐、写入执行清单或新开仓。"
    mode = resolve_market_trade_mode(regime)
    if not mode.allow_ai_review:
        return "禁止新仓；候选仅影子观察，优先处理持仓风控；不从本报告选择买入标的。"
    if mode.mode == "overheat_shadow" or (
        not mode.allow_recommendation_write and mode.mode not in {"repair_review", "confirmation_only"}
    ):
        if mode.mode == "overheat_shadow":
            return "禁止新仓；可送AI/shadow对照，不写正式推荐、不执行新买入；优先处理持仓风控。"
    if not mode.allow_recommendation_write:
        return "观察买入；允许少量候选进入AI研报，但不写正式推荐，尾盘任务和人工二次确认后再决定。"
    if selected_count <= 0:
        return "观察买入；暂无可送审标的，不从本报告选择新买入，等待下一次二次确认。"
    return f"可执行买入候选 {selected_count} 只；需等 Step3 起跳板与 OMS 风控同时确认后才可执行。"


def _today_conclusion_line(ctx: Any, selected_count: int) -> str:
    mode = resolve_market_trade_mode(ctx.regime)
    if _data_quality_observe_only(getattr(ctx, "metrics", None)):
        conclusion = "数据质量降级，仅观察"
    elif not mode.allow_ai_review or mode.mode == "overheat_shadow":
        conclusion = "禁止新仓"
    elif not mode.allow_recommendation_write:
        conclusion = "观察买入"
    elif selected_count > 0:
        conclusion = "可执行买入候选"
    else:
        conclusion = "观察买入"
    return f"**今日结论**: {conclusion} | {mode.label}"


def _trigger_reason_line(ctx: Any, money_line: str) -> str:
    bench = ctx.benchmark_context or {}
    reasons = _first_non_empty_reason_group(
        bench.get("panic_reasons"),
        bench.get("repair_reasons"),
        bench.get("bear_rebound_reasons"),
    )
    if reasons:
        return "**触发原因**: " + "；".join(reasons[:3])
    return f"**触发原因**: {money_line}"


def _first_non_empty_reason_group(*groups: object) -> list[str]:
    for group in groups:
        values = [str(x).strip() for x in (group or []) if str(x).strip()]
        if values:
            return values
    return []


def _tomorrow_action_line(ctx: Any, selected_count: int) -> str:
    mode = resolve_market_trade_mode(ctx.regime)
    if _data_quality_observe_only(getattr(ctx, "metrics", None)):
        action = "禁止正式推荐和新仓；修复数据覆盖后重新运行漏斗，不使用本次候选下单。"
    elif not mode.allow_ai_review:
        action = "禁止新仓；不用旧报告下单，只处理持仓风控，观察主线修复是否延续。"
    elif mode.mode == "overheat_shadow":
        action = "禁止新仓；AI/shadow 可对照，不写推荐、不执行新买，只处理持仓风控。"
    elif not mode.allow_recommendation_write:
        action = "观察买入；看 Step3 与尾盘任务的二次确认，不自动写推荐，不自动开仓。"
    elif selected_count > 0:
        action = "可执行买入候选；只在尾盘确认未破支撑、未冲高回落、量价健康后再考虑。"
    else:
        action = "观察买入；等待下一轮漏斗或尾盘二次确认，不提前追。"
    return f"**明日动作**: {action}"


def _candidate_brief_line(ctx: Any, selected_count: int) -> str:
    return (
        f"**候选摘要**: AI输入{selected_count}只 / 买点确认{ctx.unique_hit_count}只 / "
        f"主线买点候选{len(ctx.mainline_tradeable)}只 / 观察池{len(ctx.theme_candidate_map)}只"
    )


def _pool_summary_line(metrics: dict) -> str:
    bse = int(metrics.get("pool_bse") or 0)
    bse_part = f" + 北交{bse}" if bse > 0 else ""
    pool_limit = int(metrics.get("pool_limit") or 0)
    limit_part = f"，快扫前{pool_limit}只" if pool_limit > 0 else ""
    return (
        f"**股票池**: 主板{metrics['pool_main']} + 创业板{metrics['pool_chinext']} "
        f"+ 科创板{metrics['pool_star']}{bse_part} -> 去重{metrics['pool_merged']} "
        f"-> 去ST{metrics['pool_st_excluded']} = {metrics['total_symbols']} "
        f"(共{metrics['pool_batches']}批{limit_part})"
    )


def _data_quality_observe_only(metrics: dict | None) -> bool:
    return ((metrics or {}).get("data_quality") or {}).get("trade_readiness") == "observe_only"


def _data_quality_report_lines(metrics: dict) -> list[str]:
    quality = metrics.get("data_quality") or {}
    coverage = quality.get("coverage") or {}
    status = str(quality.get("status") or "unknown")
    readiness = str(quality.get("trade_readiness") or "unknown")
    reasons = ", ".join(quality.get("reasons") or []) or "无"
    source_counts = quality.get("ohlcv_source_counts") or {}
    sources = ", ".join(f"{source}={count}" for source, count in source_counts.items()) or "unknown=0"
    financial_coverage = _percent(coverage.get("financial")) if quality.get("financial_requested") else "未纳入量价漏斗"
    rejection_parts = []
    for layer, item in (metrics.get("layer_rejections") or {}).items():
        label = str(layer).replace("layer", "L")
        rejection_parts.append(
            f"{label}:{item.get('input', 0)}→{item.get('passed', 0)}"
            f"(淘汰{item.get('rejected', 0)}:{item.get('reason', '')})"
        )
    return [
        f"**数据质量**: {status}/{readiness} | OHLCV {_percent(coverage.get('ohlcv'))} | "
        f"市值 {_percent(coverage.get('market_cap'))} | 财务 {financial_coverage} | 原因 {reasons}",
        f"**样本与来源**: RPS universe={int(metrics.get('rps_universe_count') or 0)} | OHLCV {sources}",
        f"**逐层淘汰**: {'；'.join(rejection_parts) or '无'}",
    ]


def _percent(value: object) -> str:
    try:
        return f"{float(value or 0.0):.1%}"
    except (TypeError, ValueError):
        return "0.0%"


def _market_mix_policy_line(policy: dict) -> str:
    added = policy.get("market_mix_guard_added") or []
    reason = str(policy.get("market_mix_guard_reason") or "").strip()
    if added:
        return f"**市场均衡**: 补入主板/创业候选 {', '.join(added)}，避免结果只剩科创/北交。"
    if reason:
        return f"**市场均衡**: {reason}"
    return ""


def _policy_governance_line(policy: dict) -> str:
    attribution = policy.get("_attribution_signal_weights") or policy.get("attribution_signal_weights") or {}
    attribution_meta = policy.get("_attribution_policy_meta") or policy.get("attribution_policy_meta") or {}
    merged = policy.get("_signal_weights") or policy.get("signal_weights") or {}
    selection_summary = _policy_selection_summary(attribution_meta)
    if not attribution and not merged and not selection_summary:
        return ""
    parts = []
    if attribution:
        parts.append(f"归因 {_policy_weight_text(attribution)}{format_policy_meta_text(attribution_meta)}")
    if merged:
        parts.append(f"最终 {_policy_weight_text(merged)}")
    if selection_summary:
        parts.append(selection_summary)
    return "**策略治理调权**: " + "；".join(parts)


def _policy_selection_summary(meta: dict | None) -> str:
    if not isinstance(meta, dict):
        return ""
    summary = str(meta.get("selection_action_summary") or "").strip()
    return summary if summary and summary != "候选源治理=无" else ""


def _policy_weight_text(weights: dict) -> str:
    return format_policy_weight_text(weights, limit=8, delimiter="，")


def _top_summary_lines(ctx: Any, selected_count: int, money_line: str) -> list[str]:
    lines = funnel_playbook_lines(ctx.regime, selected_count)
    lines.extend(
        [
            _today_conclusion_line(ctx, selected_count),
            _trigger_reason_line(ctx, money_line),
            _tomorrow_action_line(ctx, selected_count),
            _candidate_brief_line(ctx, selected_count),
            "",
        ]
    )
    return lines


def _candidate_list_note(mode, *, data_quality_observe_only: bool = False) -> str:
    if data_quality_observe_only:
        return "数据质量降级：以下仅供 shadow 观察，不是买入或正式推荐清单。"
    if not mode.allow_ai_review:
        return "今日禁止新仓：以下只供观察，不是买入清单。"
    if mode.mode == "overheat_shadow":
        return "过热市禁止新开：以下仅供 AI/shadow 对照，不可写正式推荐或下单。"
    if not mode.allow_recommendation_write:
        return "观察买入：以下需 Step3 + 尾盘二次确认，当前不可直接下单。"
    return "可送审清单：优先 [主线]；再等 Step3 起跳板 + confirmed + 尾盘 BUY 才执行。"


def _candidate_list_row(ctx: Any, selection: FunnelAiSelection, code: str) -> str:
    name = ctx.name_map.get(code, code)
    track = selected_track(selection, code)
    track_badge = f"[{track}] " if track else ""
    score = display_score(ctx, selection, code)
    theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
    return f"  {track_badge}{code} {name}  {score:.2f}{_confirmation_suffix(ctx, code)}{theme_badge}"


def _top_candidate_list_lines(ctx: Any, selection: FunnelAiSelection) -> list[str]:
    selected_for_ai = selection.selected_for_ai
    mode = resolve_market_trade_mode(ctx.regime)
    lines = [
        f"**【✅ 今日候选清单】{len(selected_for_ai)} 只**",
        _candidate_list_note(
            mode,
            data_quality_observe_only=_data_quality_observe_only(getattr(ctx, "metrics", None)),
        ),
    ]
    if not selected_for_ai:
        lines.append("  无")
    else:
        ranked = sorted(selected_for_ai, key=lambda c: -display_score(ctx, selection, c))
        lines.extend(_candidate_list_row(ctx, selection, code) for code in ranked)
    lines.append("")
    return lines


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
    lines.append(f"**【👁 形态旁路观察】{len(ctx.l2_bypass_pool)} 只**")
    lines.append(f"结构强度不足但出现买点形态，按形态分数排序；送AI复核 {selected_count} 只")
    display_pool = (
        ctx.l2_bypass_ranked if FUNNEL_BYPASS_DISPLAY_LIMIT <= 0 else ctx.l2_bypass_ranked[:FUNNEL_BYPASS_DISPLAY_LIMIT]
    )
    for code in display_pool:
        name = ctx.name_map.get(code, code)
        reasons = "+".join(_trigger_short_reasons(code, ctx.bypass_triggers))
        industry = str(ctx.sector_map.get(code, "") or "")
        theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
        lines.append(f"  {code} {name}  {reasons}{_confirmation_suffix(ctx, code)}  [{industry}]{theme_badge}")
    omitted = len(ctx.l2_bypass_pool) - len(display_pool)
    if omitted > 0:
        lines.append(f"  ... 另 {omitted} 只略")


def _append_strategic_bypass_card_section(lines: list[str], ctx: Any, selected_count: int) -> None:
    if not ctx.strategic_l2_bypass_pool:
        return
    lines.append("")
    lines.append(f"**【🧭 战略主题观察】{len(ctx.strategic_l2_bypass_pool)} 只**")
    lines.append(f"基础准入通过但结构强度不足，需同时满足战略观察池与买点/阶段复核；送AI复核 {selected_count} 只")
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
        lines.append(f"  {code} {name}  {reason}{_confirmation_suffix(ctx, code)}{theme_badge}")
    omitted = len(ctx.strategic_l2_bypass_pool) - len(display_pool)
    if omitted > 0:
        lines.append(f"  ... 另 {omitted} 只略")


def _append_mainline_card_section(lines: list[str], ctx: Any, selected_count: int) -> None:
    if not ctx.mainline_candidates:
        return
    lines.append("")
    lines.append(f"**【🎯 主线买点候选】{len(ctx.mainline_tradeable)} 只**")
    lines.append(f"动态主线候选，仍需市场总闸和尾盘确认；送AI复核 {selected_count} 只")
    display_rows = _mainline_display_rows(ctx.mainline_tradeable)
    if not display_rows:
        lines.append("  暂无")
    for item in display_rows:
        lines.append(_mainline_row(ctx, item))
    omitted = len(ctx.mainline_tradeable) - len(display_rows)
    if omitted > 0:
        lines.append(f"  ... 另 {omitted} 只略")
    lines.append(f"**主线观察**: {len(ctx.mainline_observe)}只；**鱼尾不追**: {len(ctx.mainline_overheated)}只")


def _mainline_display_rows(rows: list[dict]) -> list[dict]:
    ranked = sorted(rows, key=lambda item: (-float(item.get("mainline_score") or 0.0), str(item.get("code"))))
    return ranked if FUNNEL_MAINLINE_DISPLAY_LIMIT <= 0 else ranked[:FUNNEL_MAINLINE_DISPLAY_LIMIT]


def _mainline_row(ctx: Any, item: dict) -> str:
    code = str(item.get("code") or "")
    name = str(item.get("name") or ctx.name_map.get(code) or code)
    theme = str(item.get("theme") or "")
    status = str(item.get("status") or "主线买点候选")
    entry = str(item.get("entry_type") or "等待确认")
    score = float(item.get("mainline_score") or 0.0) * 100.0
    risk = " / ".join(item.get("risk_flags") or [])
    risk_suffix = f"  风险:{risk}" if risk else ""
    metrics = item.get("metrics") or {}
    force = float(metrics.get("main_force_score") or 0.0)
    force_suffix = f"  主力分{force:.2f}" if force > 0 else ""
    return (
        f"  {code} {name}  {theme}  {status}  {entry}  分{score:.1f}"
        f"{force_suffix}{_confirmation_suffix(ctx, code)}{risk_suffix}"
    )


def _confirmation_suffix(ctx: Any, code: str) -> str:
    label = _confirmation_label(ctx, code)
    return f"  {label}" if label else ""


def _confirmation_label(ctx: Any, code: str) -> str:
    df = (getattr(ctx, "all_df_map", {}) or {}).get(code)
    if df is None or df.empty:
        return ""
    scores = []
    for signal_type in _confirmation_signal_keys(ctx, code):
        try:
            scores.append(score_springboard_abc(df, signal_type))
        except Exception:
            continue
    if not scores:
        return ""
    best = max(scores, key=lambda item: (int(item.get("met_count") or 0), str(item.get("grade") or "")))
    grade = str(best.get("grade") or "none")
    met_count = int(best.get("met_count") or 0)
    return f"二次确认:{grade}({met_count}/3)"


def _confirmation_signal_keys(ctx: Any, code: str) -> list[str]:
    keys = list((getattr(ctx, "code_to_trigger_keys", {}) or {}).get(code, []) or [])
    entry = (getattr(ctx, "candidate_entry_map", {}) or {}).get(code) or {}
    entry_key = candidate_entry_key(entry, fields=("signal_key", "lane", "entry_type"))
    if entry_key:
        keys.append(entry_key)
    if code in getattr(ctx, "mainline_candidate_set", set()):
        keys.append("mainline")
    out: list[str] = []
    for key in keys:
        if key and key not in out:
            out.append(key)
    return out


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
            lines.append(
                f"{score_star(score)} {code} {name}  {score:.2f}  {short}{_confirmation_suffix(ctx, code)}{theme_badge}"
            )
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
            lines.append(
                f"{score_star(score)} {code} {name}  {score:.2f}{_confirmation_suffix(ctx, code)}{theme_badge}"
            )
        lines.append("")


def _build_legacy_card_lines(ctx: Any, selection: FunnelAiSelection) -> list[str]:
    bench_line, money_line, amount_line, pv_line, pv_shadow_line = _market_report_lines(ctx.benchmark_context)
    selected_for_ai = selection.selected_for_ai
    lines = _top_summary_lines(ctx, len(selected_for_ai), money_line)
    lines.extend(_top_candidate_list_lines(ctx, selection))
    lines += [
        _pool_summary_line(ctx.metrics),
        f"**筛选概览**: {ctx.metrics['total_symbols']}只 → 基础准入:{ctx.metrics['layer1']} "
        f"→ 结构强度:{ctx.metrics['layer2']} → 题材共振:{ctx.metrics['layer3']} → 买点确认事件:{ctx.metrics['total_hits']}",
        f"**大盘水温**: {bench_line}",
        f"**今日交易模式**: {_trade_mode_report_line(ctx.regime)}",
        f"**明日执行结论**: {_execution_decision_line(ctx.regime, len(selected_for_ai), ctx.metrics.get('data_quality'))}",
        *_data_quality_report_lines(ctx.metrics),
        f"**大盘资金趋势**: {money_line}",
        *_capital_migration_report_lines(ctx.metrics),
        _hot_events_report_line(ctx.metrics),
        _theme_activity_report_line(ctx.metrics),
        f"**成交额分布**: {amount_line}",
        f"**大盘量价推演**: {pv_line}",
        f"**推演策略 Shadow**: {pv_shadow_line or '无'}",
        f"**中长线主线**: {summarize_theme_radar(ctx.metrics.get('theme_radar') or {})} ({ctx.theme_radar_source})",
        f"**潜在大涨候选板**: {len(ctx.candidate_entries)}只 / 类型 {ctx.metrics.get('candidate_entry_types', {}) or {}}",
        (
            f"**战略主线联动**: 观察池{len(ctx.theme_candidate_map)}只 / 买点确认{ctx.theme_l4_count}只 / "
            f"战略主题观察{len(ctx.strategic_l2_bypass_pool)}只 / "
            f"主线买点候选{len(ctx.mainline_tradeable)}只 / 加权送审{selection.theme_promoted_count}只"
        ),
        f"**候选池**: 买点确认{ctx.unique_hit_count}只 / 形态旁路{len(ctx.l2_bypass_pool)}只 "
        f"-> AI输入{len(selected_for_ai)}只 "
        f"(买点确认 {sum(1 for c in selected_for_ai if c in ctx.formal_hit_set)} / "
        f"形态旁路 {sum(1 for c in selected_for_ai if c in ctx.l2_bypass_set)} / "
        f"战略主题 {sum(1 for c in selected_for_ai if c in ctx.strategic_l2_bypass_set)} / "
        f"主线 {sum(1 for c in selected_for_ai if c in ctx.mainline_candidate_set)}; "
        f"旁路预算 {FUNNEL_L2_BYPASS_AI_CAP or 'unlimited'})",
        f"**候选集中概念**: {', '.join(ctx.metrics['top_sectors']) if ctx.metrics['top_sectors'] else '无'}",
        "",
    ]
    if ctx.external_seed_line:
        lines.insert(-1, f"**外部观察 Shadow**: {ctx.external_seed_line}")
    mix_line = _market_mix_policy_line(selection.ai_policy)
    if mix_line:
        lines.insert(-1, mix_line)
    governance_line = _policy_governance_line(selection.ai_policy)
    if governance_line:
        lines.insert(-1, governance_line)
    append_etf_section(lines, ctx.etf_metrics, ctx.etf_candidates, display_limit=FUNNEL_ETF_DISPLAY_LIMIT)
    if ctx.etf_metrics or ctx.etf_candidates:
        lines.append("")
    _append_legacy_selected_sections(lines, ctx, selected_for_ai)
    if not selected_for_ai:
        lines.append("无")
    _append_mainline_card_section(lines, ctx, sum(1 for c in selected_for_ai if c in ctx.mainline_candidate_set))
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
    mainline_selected = sum(1 for c in selected if c in ctx.mainline_candidate_set)
    return {
        "formal_event": sum(len(v) for v in ctx.formal_triggers.values()),
        "hit_selected": hit_selected,
        "bypass_selected": bypass_selected,
        "strategic_selected": strategic_selected,
        "mainline_selected": mainline_selected,
        "l3_only": max(len(selected) - hit_selected - bypass_selected - strategic_selected - mainline_selected, 0),
    }


def _print_modern_selection_summary(ctx: Any, selection: FunnelAiSelection, counts: dict[str, int]) -> None:
    policy = selection.ai_policy
    print(
        f"[funnel] 候选池: 买点确认事件={counts['formal_event']}, 买点确认股票={ctx.unique_hit_count}, "
        f"形态旁路={len(ctx.l2_bypass_pool)}, review候选={ctx.review_unique_count}, "
        f"配额配置=[{ctx.regime}->{policy['quota_family']}: requested Trend={policy['requested_trend_quota']}, "
        f"requested Accum={policy['requested_accum_quota']}, effective Trend={policy['trend_quota']}, "
        f"effective Accum={policy['accum_quota']}, 总上限={policy['total_cap']}, "
        f"stage_fill_limit Trend={policy['max_trend_l3_fill']}, Accum={policy['max_accum_l3_fill']}], "
        f"最终选入: Trend={len(selection.trend_selected)}, Accum={len(selection.accum_selected)}, "
        f"战略主题={counts['strategic_selected']}, 主线={counts['mainline_selected']}, 总计={len(selection.selected_for_ai)}"
    )


def _modern_header_lines(ctx: Any, selection: FunnelAiSelection, counts: dict[str, int]) -> list[str]:
    bench_line, money_line, amount_line, pv_line, pv_shadow_line = _market_report_lines(ctx.benchmark_context)
    policy = selection.ai_policy
    lines = _top_summary_lines(ctx, len(selection.selected_for_ai), money_line) + [
        _pool_summary_line(ctx.metrics),
        f"**筛选概览**: {ctx.metrics['total_symbols']}只 → 基础准入:{ctx.metrics['layer1']} "
        f"→ 结构强度:{ctx.metrics['layer2']} → 题材共振:{ctx.metrics['layer3']} → 买点确认:{ctx.unique_hit_count}",
        f"**大盘水温**: {bench_line}",
        f"**今日交易模式**: {_trade_mode_report_line(ctx.regime)}",
        f"**明日执行结论**: {_execution_decision_line(ctx.regime, len(selection.selected_for_ai), ctx.metrics.get('data_quality'))}",
        *_data_quality_report_lines(ctx.metrics),
        f"**大盘资金趋势**: {money_line}",
        *_capital_migration_report_lines(ctx.metrics),
        _hot_events_report_line(ctx.metrics),
        _theme_activity_report_line(ctx.metrics),
        f"**成交额分布**: {amount_line}",
        f"**大盘量价推演**: {pv_line}",
        f"**推演策略 Shadow**: {pv_shadow_line or '无'}",
        f"**中长线主线**: {summarize_theme_radar(ctx.metrics.get('theme_radar') or {})} ({ctx.theme_radar_source})",
        f"**潜在大涨候选板**: {len(ctx.candidate_entries)}只 / 类型 {ctx.metrics.get('candidate_entry_types', {}) or {}}",
        (
            f"**战略主线联动**: 观察池{len(ctx.theme_candidate_map)}只 / 买点确认{ctx.theme_l4_count}只 / "
            f"战略主题观察{len(ctx.strategic_l2_bypass_pool)}只 / "
            f"主线买点候选{len(ctx.mainline_tradeable)}只 / 主线送审{selection.mainline_promoted_count}只"
        ),
        f"**候选池**: 买点确认{ctx.unique_hit_count}只 / 形态旁路{len(ctx.l2_bypass_pool)}只 "
        f"-> AI输入{len(selection.selected_for_ai)}只 "
        f"(配额 {policy['quota_family']}: Trend {len(selection.trend_selected)}/{policy['trend_quota']}, "
        f"Accum {len(selection.accum_selected)}/{policy['accum_quota']}; 买点确认 {counts['hit_selected']} / "
        f"阶段补位{counts['l3_only']} / 形态旁路 {counts['bypass_selected']} / "
        f"战略主题 {counts['strategic_selected']} / 主线 {counts['mainline_selected']}; "
        f"旁路预算 {FUNNEL_L2_BYPASS_AI_CAP or 'unlimited'})",
        f"**候选集中概念**: {', '.join(ctx.metrics['top_sectors']) if ctx.metrics['top_sectors'] else '无'}",
        "",
    ]
    if ctx.external_seed_line:
        lines.insert(-1, f"**外部观察 Shadow**: {ctx.external_seed_line}")
    mix_line = _market_mix_policy_line(policy)
    if mix_line:
        lines.insert(-1, mix_line)
    governance_line = _policy_governance_line(policy)
    if governance_line:
        lines.insert(-1, governance_line)
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
        if c not in ctx.formal_hit_set
        and c not in ctx.l2_bypass_set
        and c not in ctx.strategic_l2_bypass_set
        and c not in ctx.mainline_candidate_set
    ]
    if not fill_codes:
        return
    lines.append(f"**【🧭 板块阶段补位】{len(fill_codes)} 只**")
    for code in sorted(fill_codes, key=lambda c: -display_score(ctx, selection, c)):
        name = ctx.name_map.get(code, code)
        stage = stage_name(ctx, code)
        channel = str(ctx.l2_channel_map.get(code, "")).strip()
        suffix = " / ".join(x for x in [stage, channel] if x)
        score = display_score(ctx, selection, code)
        theme_badge = f"  {ctx.theme_badge_map[code]}" if code in ctx.theme_badge_map else ""
        lines.append(
            f"{score_star(score)} {code} {name}  {score:.2f}"
            + (f"  {suffix}" if suffix else "")
            + _confirmation_suffix(ctx, code)
            + theme_badge
        )
    lines.append("")


def _append_modern_strategic_bypass_section(lines: list[str], ctx: Any, selected_count: int) -> None:
    if not ctx.strategic_l2_bypass_pool:
        return
    lines.append("")
    lines.append(f"**【🧭 战略主题观察】{len(ctx.strategic_l2_bypass_pool)} 只**")
    lines.append(f"基础准入通过但结构强度不足，需同时满足战略观察池与买点/阶段复核；送AI复核 {selected_count} 只")
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
        lines.append(f"  {code} {name}  {reason}{_confirmation_suffix(ctx, code)}{theme_badge}")
    omitted = len(ctx.strategic_l2_bypass_pool) - len(display_pool)
    if omitted > 0:
        lines.append(f"  ... 另 {omitted} 只略")


def _build_modern_card_lines(ctx: Any, selection: FunnelAiSelection) -> list[str]:
    counts = _modern_selection_counts(ctx, selection)
    _print_modern_selection_summary(ctx, selection, counts)
    lines = _modern_header_lines(ctx, selection, counts)
    lines.extend(_top_candidate_list_lines(ctx, selection))
    append_etf_section(lines, ctx.etf_metrics, ctx.etf_candidates, display_limit=FUNNEL_ETF_DISPLAY_LIMIT)
    if ctx.etf_metrics or ctx.etf_candidates:
        lines.append("")
    if ctx.formal_sorted_codes:
        lines.append("**买点确认展开**: 以下列出全部买点确认候选；标记 →AI 的进入 Step3 研报")
        append_formal_l4_sections(
            lines,
            ctx.formal_sorted_codes,
            selection.selected_for_ai,
            ctx.name_map,
            ctx.code_to_trigger_keys,
            lambda code: display_score(ctx, selection, code),
            ctx.theme_badge_map,
            lambda code: _confirmation_label(ctx, code),
        )
    _append_modern_fill_section(lines, ctx, selection)
    if not selection.selected_for_ai:
        lines.append("无")
    _append_mainline_card_section(lines, ctx, counts["mainline_selected"])
    _append_l2_bypass_card_section(lines, ctx, counts["bypass_selected"])
    _append_modern_strategic_bypass_section(lines, ctx, counts["strategic_selected"])
    return lines
