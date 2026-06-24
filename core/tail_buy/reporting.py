from __future__ import annotations

from core.tail_buy.models import DECISION_BUY, DECISION_SKIP, DECISION_WATCH, TailBuyCandidate


def summarize_decision_counts(candidates: list[TailBuyCandidate]) -> dict[str, int]:
    out = {DECISION_BUY: 0, DECISION_WATCH: 0, DECISION_SKIP: 0}
    for item in candidates or []:
        decision = str(item.final_decision or "").strip().upper()
        if decision in out:
            out[decision] += 1
    return out


def _clean_extra_sections(extra_sections: list[str] | None) -> list[str]:
    return [text for section in extra_sections or [] if (text := str(section or "").strip())]


def _header_lines(
    *,
    now_text: str,
    source_text: str,
    candidates: list[TailBuyCandidate],
    counts: dict[str, int],
    llm_total: int,
    llm_success: int,
    elapsed_seconds: float,
    buy_only: bool,
    data_fetched_at: str,
    market_reminder: str,
) -> list[str]:
    layer_text = f"- 分层结果: BUY={counts[DECISION_BUY]}"
    if not buy_only:
        layer_text += f" / WATCH={counts[DECISION_WATCH]} / SKIP={counts[DECISION_SKIP]}"
    return [
        f"⏰ Tail Buy {now_text}",
        "",
        f"- 候选来源: {source_text}",
        f"- 扫描数量: {len(candidates)}",
        layer_text,
        f"- AI 二判: {llm_success}/{llm_total}",
        f"- 分时数据获取: {data_fetched_at}" if data_fetched_at else "- 分时数据获取: -",
        f"- 总耗时: {elapsed_seconds:.1f}s",
        "",
        f"⚠️ 风险提醒: {market_reminder} | 安全闸: 缺支撑/防守水温单EVR/跌支撑/冲高回落不进BUY",
        "",
    ]


def _item_line(item: TailBuyCandidate) -> str:
    reasons = "；".join(item.rule_reasons[:2]) if item.rule_reasons else "规则信号一般"
    llm_tag = f" | AI:{item.llm_decision}" if item.llm_decision else ""
    llm_reason = f" | {item.llm_reason}" if item.llm_reason else ""
    add_tag = "[加仓] " if item.signal_type == "holding" else ""
    return (
        f"- {add_tag}{item.code} {item.name} | priority={item.priority_score:.1f} | "
        f"rule={item.rule_decision}({item.rule_score:.1f}){llm_tag} | {reasons}{llm_reason}"
    )


def _decision_block(
    candidates: list[TailBuyCandidate],
    *,
    title: str,
    decision: str,
    max_error_items_per_block: int,
) -> list[str]:
    block = [x for x in candidates if x.final_decision == decision]
    lines = [f"## {title}"]
    if not block:
        return lines + ["- 无", ""]
    max_errors = max(int(max_error_items_per_block), 1)
    error_items = [x for x in block if str(x.fetch_error or "").strip()]
    normal_items = [x for x in block if not str(x.fetch_error or "").strip()]
    lines.extend(_item_line(item) for item in normal_items + error_items[:max_errors])
    omitted_errors = max(len(error_items) - max_errors, 0)
    if omitted_errors > 0:
        lines.append(f"- ... 其余 {omitted_errors} 只报错标的已省略（详见日志 artifacts）")
    return lines + [""]


def _append_extra_sections(lines: list[str], extra_sections: list[str]) -> None:
    for text in extra_sections:
        lines.append(text)
        lines.append("")


def _source_text(target_signal_date: str, candidate_source: str | None) -> str:
    return str(candidate_source or "").strip() or (
        f"signal_pending（signal_date={target_signal_date}, status in pending/confirmed）"
    )


def _append_decision_sections(
    lines: list[str],
    candidates: list[TailBuyCandidate],
    *,
    max_error_items_per_block: int,
    buy_only: bool,
) -> None:
    sections = [("BUY（优先关注）", DECISION_BUY)]
    if not buy_only:
        sections.extend([("WATCH（观察）", DECISION_WATCH), ("SKIP（暂不买入）", DECISION_SKIP)])
    for title, decision in sections:
        lines.extend(
            _decision_block(
                candidates,
                title=title,
                decision=decision,
                max_error_items_per_block=max_error_items_per_block,
            )
        )


def build_tail_buy_markdown(
    *,
    now_text: str,
    target_signal_date: str,
    market_reminder: str,
    candidates: list[TailBuyCandidate],
    llm_total: int,
    llm_success: int,
    elapsed_seconds: float,
    extra_sections: list[str] | None = None,
    extra_sections_first: bool = False,
    max_error_items_per_block: int = 5,
    candidate_source: str | None = None,
    buy_only: bool = False,
    data_fetched_at: str = "",
) -> str:
    lines = _header_lines(
        now_text=now_text,
        source_text=_source_text(target_signal_date, candidate_source),
        candidates=candidates,
        counts=summarize_decision_counts(candidates),
        llm_total=llm_total,
        llm_success=llm_success,
        elapsed_seconds=elapsed_seconds,
        buy_only=buy_only,
        data_fetched_at=data_fetched_at,
        market_reminder=market_reminder,
    )
    cleaned_sections = _clean_extra_sections(extra_sections)
    if extra_sections_first:
        _append_extra_sections(lines, cleaned_sections)
    _append_decision_sections(
        lines,
        candidates,
        max_error_items_per_block=max_error_items_per_block,
        buy_only=buy_only,
    )
    if not extra_sections_first:
        _append_extra_sections(lines, cleaned_sections)
    lines.append("说明：BUY=可行动；WATCH=观察；SKIP=禁买/暂不买。本任务不生成订单，不写入交易表。")
    return "\n".join(lines).strip() + "\n"
