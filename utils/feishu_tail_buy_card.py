"""Feishu rich-card elements for Tail Buy reports."""

from __future__ import annotations

import os
from dataclasses import dataclass

from integrations.tickflow_notice import (
    TICKFLOW_LIMIT_HINT,
    append_tickflow_limit_hint,
    has_recent_tickflow_limit_event,
)
from utils.feishu_text import annotate_financial_terms, lark_md_div, lark_note

HOLDING_HEADINGS = ("持仓动作建议（硬止损/结构减仓/洗盘观察）", "持仓动作建议（加仓/减仓）")


@dataclass(frozen=True)
class TailBuyCardLimits:
    max_buy: int
    max_watch: int
    max_skip: int
    max_hold_each: int
    item_char_limit: int


@dataclass(frozen=True)
class TailBuyReportSections:
    annotated: str
    run_line: str
    source: str
    scan_count: str
    decision_line: str
    llm_line: str
    route_line: str
    data_fetched_line: str
    elapsed_line: str
    risk_line: str
    holding_source: str
    holding_count: str
    holding_distribution: str
    add_items: list[str]
    trim_items: list[str]
    wash_items: list[str]
    weak_items: list[str]
    hold_items: list[str]
    buy_items: list[str]
    risk_buy_items: list[str]
    watch_items: list[str]
    skip_items: list[str]


def _extract_line(lines: list[str], prefix: str) -> str:
    for raw in lines:
        text = raw.strip()
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
    return ""


def _extract_section_items(lines: list[str], heading: str) -> list[str]:
    target = f"## {heading}"
    in_section = False
    out: list[str] = []
    for raw in lines:
        text = raw.strip()
        if text == target:
            in_section = True
            continue
        if in_section and text.startswith("## "):
            break
        if in_section and text.startswith("- "):
            out.append(text[2:].strip())
    return out


def _extract_subsection_items(lines: list[str], parent_heading: str, sub_heading: str) -> list[str]:
    parent = f"## {parent_heading}"
    sub = f"### {sub_heading}"
    in_parent = False
    in_sub = False
    out: list[str] = []
    for raw in lines:
        text = raw.strip()
        if text == parent:
            in_parent = True
            in_sub = False
            continue
        if in_parent and text.startswith("## ") and text != parent:
            break
        if in_parent and text == sub:
            in_sub = True
            continue
        if in_sub and text.startswith("### ") and text != sub:
            break
        if in_sub and text.startswith("- "):
            out.append(text[2:].strip())
    return out


def _extract_first_subsection_items(
    lines: list[str],
    parent_headings: tuple[str, ...],
    sub_headings: tuple[str, ...],
) -> list[str]:
    for parent in parent_headings:
        for sub in sub_headings:
            items = _extract_subsection_items(lines, parent, sub)
            if items:
                return items
    return []


def _trim_text(text: str, limit: int) -> str:
    clean = str(text or "").strip().replace("<", "&lt;").replace(">", "&gt;")
    if int(limit) <= 0:
        return clean
    if len(clean) <= max(limit, 32):
        return clean
    return clean[: max(limit, 32) - 1] + "…"


def _format_item(item: str, item_char_limit: int) -> str:
    text = _trim_text(item, item_char_limit)
    if not text:
        return "- -"
    if text in {"无", "none", "None"}:
        return "- 无"
    if " | " in text:
        head, tail = text.split(" | ", 1)
        return f"- **{head.strip()}** | {tail.strip()}"
    return f"- {text}"


def _safe_int(raw: str, default: int) -> int:
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _card_limits() -> TailBuyCardLimits:
    return TailBuyCardLimits(
        max_buy=_safe_int(os.getenv("FEISHU_TAIL_BUY_MAX_BUY", "0"), 0),
        max_watch=_safe_int(os.getenv("FEISHU_TAIL_BUY_MAX_WATCH", "0"), 0),
        max_skip=_safe_int(os.getenv("FEISHU_TAIL_BUY_MAX_SKIP", "0"), 0),
        max_hold_each=_safe_int(os.getenv("FEISHU_TAIL_BUY_MAX_HOLDING_EACH", "0"), 0),
        item_char_limit=_safe_int(os.getenv("FEISHU_TAIL_BUY_ITEM_CHAR_LIMIT", "0"), 0),
    )


def _report_sections(content: str) -> TailBuyReportSections:
    annotated = annotate_financial_terms(append_tickflow_limit_hint(content))
    lines = annotated.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    return TailBuyReportSections(
        annotated=annotated,
        run_line=next((x.strip() for x in lines if x.strip().startswith("⏰ Tail Buy ")), "⏰ Tail Buy"),
        source=_extract_line(lines, "- 候选来源:"),
        scan_count=_extract_line(lines, "- 扫描数量:"),
        decision_line=_extract_line(lines, "- 分层结果:"),
        llm_line=_extract_line(lines, "- LLM 二判:"),
        route_line=_extract_line(lines, "- LLM 路由:"),
        data_fetched_line=_extract_line(lines, "- 分时数据获取:"),
        elapsed_line=_extract_line(lines, "- 总耗时:"),
        risk_line=next((x.strip() for x in lines if x.strip().startswith("⚠️ 风险提醒:")), ""),
        holding_source=_extract_line(lines, "- 持仓来源:"),
        holding_count=_extract_line(lines, "- 持仓数量:"),
        holding_distribution=_extract_line(lines, "- 动作分布:"),
        add_items=_extract_first_subsection_items(lines, HOLDING_HEADINGS, ("ADD（可考虑加仓）",)),
        trim_items=_extract_first_subsection_items(
            lines,
            HOLDING_HEADINGS,
            ("TRIM（硬止损/确认破位，优先处理）", "TRIM（可考虑减仓）"),
        ),
        wash_items=_extract_first_subsection_items(lines, HOLDING_HEADINGS, ("WASH（疑似洗盘/回踩测试，不直接卖）",)),
        weak_items=_extract_first_subsection_items(lines, HOLDING_HEADINGS, ("WEAK（尾盘转弱待确认）",)),
        hold_items=_extract_first_subsection_items(
            lines,
            HOLDING_HEADINGS,
            ("HOLD（结构中性持有观察）", "HOLD（持有观察）"),
        ),
        buy_items=_extract_section_items(lines, "BUY（可执行候选）")
        or _extract_section_items(lines, "BUY（优先关注）"),
        risk_buy_items=_extract_section_items(lines, "BUY（高位动能观察，默认不买）"),
        watch_items=_extract_section_items(lines, "WATCH（观察）"),
        skip_items=_extract_section_items(lines, "SKIP（暂不买入）"),
    )


def _tail_buy_column(label: str, value: str) -> dict:
    return {
        "tag": "column",
        "width": "weighted",
        "weight": 1,
        "elements": [lark_md_div(f"**{label}**\n{value or '-'}")],
    }


def _add_bucket(
    elements: list[dict],
    title_text: str,
    items: list[str],
    max_items: int,
    item_char_limit: int,
) -> None:
    safe_items = [item for item in items if item]
    elements.append(lark_md_div(f"**{title_text}**"))
    if not safe_items:
        elements.append(lark_md_div("- 无"))
        return
    shown = safe_items[:max_items] if int(max_items) > 0 else safe_items
    elements.append(lark_md_div("\n".join(_format_item(item, item_char_limit) for item in shown)))
    omitted = max(len(safe_items) - len(shown), 0)
    if omitted > 0:
        elements.append(lark_note(f"{title_text} 其余 {omitted} 条已折叠（完整明细见 TG / 日志）"))


def _summary_elements(sections: TailBuyReportSections) -> list[dict]:
    elements = [_summary_header(sections), _summary_columns(sections)]
    if sections.route_line:
        elements.append(lark_md_div(f"LLM 路由：`{sections.route_line}`"))
    if sections.data_fetched_line:
        elements.append(lark_md_div(f"分时数据获取：`{sections.data_fetched_line}`"))
    if sections.risk_line:
        elements.append(lark_note(sections.risk_line))
    return elements


def _summary_header(sections: TailBuyReportSections) -> dict:
    line = f"**{sections.run_line}**"
    if sections.source:
        line += f"\n候选来源：`{sections.source}`"
    return lark_md_div(line)


def _summary_columns(sections: TailBuyReportSections) -> dict:
    return {
        "tag": "column_set",
        "flex_mode": "stretch",
        "background_style": "grey",
        "columns": [
            _tail_buy_column("扫描", sections.scan_count),
            _tail_buy_column("分层", sections.decision_line),
            _tail_buy_column("LLM", sections.llm_line),
            _tail_buy_column("耗时", sections.elapsed_line),
        ],
    }


def _holding_elements(sections: TailBuyReportSections, limits: TailBuyCardLimits) -> list[dict]:
    elements = [{"tag": "hr"}, lark_md_div("**持仓动作建议（硬止损/结构减仓/洗盘观察）**")]
    elements.extend(_holding_meta_elements(sections))
    _add_bucket(elements, "ADD（可考虑加仓）", sections.add_items, limits.max_hold_each, limits.item_char_limit)
    _add_bucket(elements, "TRIM（硬止损/确认破位）", sections.trim_items, limits.max_hold_each, limits.item_char_limit)
    _add_bucket(elements, "WASH（疑似洗盘观察）", sections.wash_items, limits.max_hold_each, limits.item_char_limit)
    _add_bucket(elements, "WEAK（弱势待确认）", sections.weak_items, limits.max_hold_each, limits.item_char_limit)
    _add_bucket(elements, "HOLD（结构中性）", sections.hold_items, limits.max_hold_each, limits.item_char_limit)
    return elements


def _holding_meta_elements(sections: TailBuyReportSections) -> list[dict]:
    elements: list[dict] = []
    if sections.holding_source:
        elements.append(lark_md_div(f"- {sections.holding_source}"))
    if sections.holding_count:
        elements.append(lark_md_div(f"- 持仓数量：{sections.holding_count}"))
    if sections.holding_distribution:
        elements.append(lark_md_div(f"- 动作分布：{sections.holding_distribution}"))
    return elements


def _candidate_elements(sections: TailBuyReportSections, limits: TailBuyCardLimits) -> list[dict]:
    elements: list[dict] = [{"tag": "hr"}]
    _add_bucket(elements, "BUY（可执行候选）", sections.buy_items, limits.max_buy, limits.item_char_limit)
    _add_bucket(
        elements, "BUY（高位动能观察，默认不买）", sections.risk_buy_items, limits.max_buy, limits.item_char_limit
    )
    _add_bucket(elements, "WATCH（观察）", sections.watch_items, limits.max_watch, limits.item_char_limit)
    _add_bucket(elements, "SKIP（暂不买入）", sections.skip_items, limits.max_skip, limits.item_char_limit)
    return elements


def _footer_elements(sections: TailBuyReportSections) -> list[dict]:
    elements = [{"tag": "hr"}, lark_note("说明：本任务仅输出尾盘扫描建议，不生成订单，不写入交易表。")]
    if has_recent_tickflow_limit_event() or TICKFLOW_LIMIT_HINT in sections.annotated:
        elements.append(lark_note(f"⚠️ {TICKFLOW_LIMIT_HINT}"))
    return elements


def build_tail_buy_card_elements(content: str) -> list[dict]:
    sections = _report_sections(content)
    limits = _card_limits()
    return (
        _summary_elements(sections)
        + _holding_elements(sections, limits)
        + _candidate_elements(sections, limits)
        + _footer_elements(sections)
    )
