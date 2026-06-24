"""Markdown report rendering for limit-up replay reviews."""

from __future__ import annotations

from collections import Counter
from datetime import date


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
        "**逐票复盘（在前一日漏斗中止步层级与原因）**",
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
    lines.extend(_l2_focus(stage_rows.get("L2淘汰", []), total))
    lines.extend(_risk_focus(stage_rows.get("风控淘汰[触发结构止损或派发]", [])))
    lines.extend(_l4_miss_focus(stage_rows.get("L4未命中", [])))
    lines.extend(_l3_focus(stage_rows.get("L3淘汰", [])))
    lines.extend(_l1_focus(stage_rows.get("L1淘汰", [])))
    lines.extend(_l4_hit_focus(stage_rows.get("L4命中", [])))
    return lines


def _l2_focus(rows: list[dict[str, str]], total: int) -> list[str]:
    if not rows:
        return []
    pct = len(rows) / total * 100.0
    return [
        f"- **L2 是主因**：{len(rows)} / {total}（{pct:.1f}%）前一日没有进入六通道。这里不宜直接放宽实盘漏斗，否则会把大量无结构、纯事件驱动的一日异动混入候选池。"
    ]


def _risk_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [
        f"- **风控冲突优先复盘**：{short_code_list(rows)}。这些票已进入后续层，但被结构止损/派发硬剔除，最适合单独检查止损是否对节后修复过敏。"
    ]


def _l4_miss_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [
        f"- **L4 扳机漏网**：{short_code_list(rows)}。这些票已过 L2/L3，只差 Spring/LPS/EVR/SOS 微观触发，适合测试“爆发前夜压缩/试盘”类观察信号。"
    ]


def _l3_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [f"- **板块层漏网**：{short_code_list(rows)}。若同一题材后续反复出现，可考虑给极强个股更多行业绕行权。"]


def _l1_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [f"- **基础过滤漏网**：{short_code_list(rows)}。主要是成交额/基础流动性，不建议为涨停复盘反向放宽。"]


def _l4_hit_focus(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    return [f"- **已被漏斗捕获**：{short_code_list(rows)}。这类不是形态漏检，后续应核对是否被 AI 配额或风控环节挡住。"]


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
