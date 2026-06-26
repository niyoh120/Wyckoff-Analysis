"""Markdown report rendering for limit-up replay reviews."""

from __future__ import annotations

from collections import Counter
from datetime import date

from core.funnel_taxonomy import (
    REVIEW_STAGE_BASE_REJECT,
    REVIEW_STAGE_CANDIDATE_HIT,
    REVIEW_STAGE_RISK_BLOCK,
    REVIEW_STAGE_STRENGTH_MISS,
    REVIEW_STAGE_THEME_MISS,
    REVIEW_STAGE_TRIGGER_HIT,
    REVIEW_STAGE_TRIGGER_MISS,
)


def short_code_list(rows: list[dict[str, str]], limit: int = 8) -> str:
    shown = [f"{row['code']}{row['name']}" for row in rows[:limit]]
    if len(rows) > limit:
        shown.append(f"等{len(rows)}只")
    return "、".join(shown) if shown else "无"


def build_focus_lines(rows: list[dict[str, str]], today: date, previous_trade_date: date) -> list[str]:
    total = max(len(rows), 1)
    stage_rows = _group_stage_rows(rows)
    lines = ["**重点归因**"]
    lines.extend(_date_gap_lines(today, previous_trade_date))
    lines.extend(_stage_focus_lines(stage_rows, total))
    return lines


def build_report_lines(
    rows: list[dict[str, str]],
    stage_counter: Counter[str],
    today: date,
    previous_trade_date: date,
    end_trade_date: str,
) -> list[str]:
    summary = " | ".join([f"{key}{value}" for key, value in stage_counter.items()]) or "无"
    recommendation_hits, recommendation_unknown = _recommendation_counts(rows)
    lines = [
        f"**今日**: {today}",
        f"**前一日漏斗**: {end_trade_date}",
        f"**今日≥+8%且今日开盘≤+4%且前一日≤+6%股票数**: {len(rows)}",
        f"**结果汇总**: {summary}",
        _recommendation_summary(len(rows), recommendation_hits, recommendation_unknown),
        "",
        *build_focus_lines(rows, today=today, previous_trade_date=previous_trade_date),
        "",
        "**逐票复盘（前一日候选链路状态与原因）**",
        "",
    ]
    lines.extend(_detail_lines(rows))
    return lines


def _group_stage_rows(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    stage_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        stage_rows.setdefault(row["stage"], []).append(row)
    return stage_rows


def _date_gap_lines(today: date, previous_trade_date: date) -> list[str]:
    gap_days = (today - previous_trade_date).days
    if gap_days <= 1:
        return []
    return [
        f"- **日期间隔**：{previous_trade_date} 收盘后到 {today} 之间跨 {gap_days} 个自然日，节假日/周末消息驱动的跳空异动，本来就很难由前一交易日日线结构提前捕获。"
    ]


def _stage_focus_lines(stage_rows: dict[str, list[dict[str, str]]], total: int) -> list[str]:
    lines: list[str] = []
    lines.extend(_candidate_hit_focus(stage_rows.get(REVIEW_STAGE_CANDIDATE_HIT, [])))
    lines.extend(_strength_miss_focus(stage_rows.get(REVIEW_STAGE_STRENGTH_MISS, []), total))
    lines.extend(_risk_focus(stage_rows.get(REVIEW_STAGE_RISK_BLOCK, [])))
    lines.extend(_trigger_miss_focus(stage_rows.get(REVIEW_STAGE_TRIGGER_MISS, [])))
    lines.extend(_theme_miss_focus(stage_rows.get(REVIEW_STAGE_THEME_MISS, [])))
    lines.extend(_base_reject_focus(stage_rows.get(REVIEW_STAGE_BASE_REJECT, [])))
    lines.extend(_trigger_hit_focus(stage_rows.get(REVIEW_STAGE_TRIGGER_HIT, [])))
    return lines


def _candidate_hit_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [
        f"- **候选池已捕获**：{short_code_list(rows)}。这些票已进入前一日多路候选池，后续重点核对 AI 配额、尾盘确认和风控是否挡住。"
    ]


def _strength_miss_focus(rows: list[dict[str, str]], total: int) -> list[str]:
    if not rows:
        return []
    pct = len(rows) / total * 100.0
    return [
        f"- **未入候选池：结构强度不足**：{len(rows)} / {total}（{pct:.1f}%）没有被主线、趋势回踩、趋势突破、板块强势或 Wyckoff 结构车道接住。"
    ]


def _risk_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [
        f"- **风控拦截优先复盘**：{short_code_list(rows)}。这些票被结构止损/派发信号硬拦截，适合单独检查止损是否对强修复过敏。"
    ]


def _trigger_miss_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [
        f"- **买点未确认**：{short_code_list(rows)}。这些票已有结构基础但未触发买点确认，适合检查“爆发前夜压缩/试盘”类车道是否需要补强。"
    ]


def _theme_miss_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [f"- **题材共振不足**：{short_code_list(rows)}。优先检查题材映射、主线热度和板块强势车道覆盖。"]


def _base_reject_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [f"- **基础准入淘汰**：{short_code_list(rows)}。主要是成交额/基础流动性，不建议为涨停复盘反向放宽。"]


def _trigger_hit_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [f"- **买点已确认**：{short_code_list(rows)}。这类不是形态漏检，后续应核对是否被 AI 配额或风控环节挡住。"]


def _recommendation_counts(rows: list[dict[str, str]]) -> tuple[int, int]:
    notes = [str(row.get("recommendation", "")).strip() for row in rows]
    hits = sum(1 for note in notes if "累计推荐" in note)
    unknown = sum(1 for note in notes if "无法确认" in note)
    return hits, unknown


def _recommendation_summary(total: int, hits: int, unknown: int) -> str:
    summary = f"**推荐表交叉检查**: 命中{hits}只 | 未推荐{total - hits - unknown}只"
    return summary + (f" | 无法确认{unknown}只" if unknown else "")


def _detail_lines(rows: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        recommendation = str(row.get("recommendation", "")).strip()
        suffix = f" | {recommendation}" if recommendation else ""
        lines.append(f"• {row['code']} {row['name']} | {row['stage']} | {row['reason']}{suffix}")
    return lines
