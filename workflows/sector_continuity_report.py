"""Report calculations for concept-sector continuity."""

from __future__ import annotations

from datetime import date


def update_history_with_trade_date(history: dict, heat: list[dict], trade_date: date) -> dict:
    today = trade_date.isoformat()
    top_items = sorted(heat, key=lambda item: item.get("net_inflow", 0), reverse=True)[:20]
    history[today] = {
        item["name"]: {"pct": item.get("pct", 0.0), "inflow": item.get("net_inflow", 0)}
        for item in top_items
        if item.get("name")
    }
    sorted_dates = sorted(history.keys(), reverse=True)[:20]
    return {day: history[day] for day in sorted_dates}


def build_sector_continuity_report(history: dict) -> str:
    sorted_dates = sorted(history.keys(), reverse=True)
    streaks = _compute_streaks(history)
    turnover_rows = _compute_daily_turnover(history)
    avg_streak = sum(streaks.values()) / len(streaks) if streaks else 0
    avg_turnover = sum(row["turnover"] for row in turnover_rows) / len(turnover_rows) if turnover_rows else 1.0
    regime = _classify_regime(avg_streak, avg_turnover)
    lines = _render_summary(sorted_dates, regime, avg_streak, avg_turnover, streaks)
    lines += _render_theme_lines(history, sorted_dates, streaks)
    lines += _render_details(history, sorted_dates, turnover_rows, regime)
    return "\n".join(lines)


def _compute_streaks(history: dict) -> dict[str, int]:
    sorted_dates = sorted(history.keys(), reverse=True)
    if not sorted_dates:
        return {}
    latest_concepts = set(history[sorted_dates[0]].keys())
    streaks: dict[str, int] = {}
    for concept in latest_concepts:
        streaks[concept] = _concept_streak(history, sorted_dates, concept)
    return dict(sorted(streaks.items(), key=lambda item: -item[1]))


def _concept_streak(history: dict, sorted_dates: list[str], concept: str) -> int:
    streak = 1
    for day in sorted_dates[1:]:
        if concept not in history.get(day, {}):
            break
        streak += 1
    return streak


def _compute_daily_turnover(history: dict) -> list[dict]:
    sorted_dates = sorted(history.keys())
    rows = []
    for idx in range(1, len(sorted_dates)):
        prev_set = set(history[sorted_dates[idx - 1]].keys())
        curr_set = set(history[sorted_dates[idx]].keys())
        if curr_set:
            rows.append(_turnover_row(sorted_dates[idx], prev_set, curr_set))
    return rows


def _turnover_row(day: str, prev_set: set[str], curr_set: set[str]) -> dict:
    new_faces = curr_set - prev_set
    return {
        "date": day,
        "turnover": len(new_faces) / len(curr_set),
        "new_count": len(new_faces),
        "total": len(curr_set),
        "new_faces": sorted(new_faces),
    }


def _classify_regime(avg_streak: float, avg_turnover: float) -> str:
    if avg_streak >= 4 and avg_turnover < 0.3:
        return "主线延续"
    if avg_streak >= 2.5 or avg_turnover < 0.45:
        return "轮动适中"
    return "一日游"


def _render_summary(
    sorted_dates: list[str], regime: str, avg_streak: float, avg_turnover: float, streaks: dict
) -> list[str]:
    return [
        "# 板块延续性报告",
        "",
        f"**分析区间**: {sorted_dates[-1]} ~ {sorted_dates[0]} ({len(sorted_dates)} 个交易日)",
        "**数据源**: 同花顺概念板块热度 Top 20（按资金净流入排序）",
        "",
        "## 延续性总览",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 当前 Regime | **{regime}** |",
        f"| Top-20 概念平均 Streak | {avg_streak:.1f} 天 |",
        f"| 日均换手率（新面孔/Top-20） | {avg_turnover:.1%} |",
        f"| 连续 ≥3 天的主线概念数 | {sum(1 for streak in streaks.values() if streak >= 3)} |",
        f"| 连续 ≥5 天的超强主线数 | {sum(1 for streak in streaks.values() if streak >= 5)} |",
        "",
    ]


def _render_theme_lines(history: dict, sorted_dates: list[str], streaks: dict) -> list[str]:
    top_streaks = [(concept, streak) for concept, streak in streaks.items() if streak >= 2]
    lines = ["## 当前主线（连续 ≥2 天）", ""]
    if not top_streaks:
        lines.extend(["*无连续 ≥2 天的概念，纯一日游行情*", ""])
        return lines
    lines.extend(["| 概念 | 连续天数 | 今日涨幅 | 今日资金净流入 |", "|------|---------|---------|--------------|"])
    today_data = history.get(sorted_dates[0], {})
    for concept, streak in top_streaks:
        lines.append(_theme_line(concept, streak, today_data.get(concept, {})))
    lines.append("")
    return lines


def _theme_line(concept: str, streak: int, info: dict) -> str:
    pct = info.get("pct", 0.0)
    inflow = info.get("inflow", 0)
    inflow_yi = inflow / 1e8 if abs(inflow) > 1e6 else inflow / 1e4
    unit = "亿" if abs(inflow) > 1e6 else "万"
    return f"| {concept} | {streak} | {pct:+.2f}% | {inflow_yi:.1f}{unit} |"


def _render_details(history: dict, sorted_dates: list[str], turnover_rows: list[dict], regime: str) -> list[str]:
    lines = ["## 每日轮动速率", "", "| 日期 | 换手率 | 新面孔数 | 新进概念 |", "|------|--------|---------|---------|"]
    lines.extend(_turnover_lines(turnover_rows))
    lines.extend(["", "## 每日 Top-10 概念", ""])
    for day in sorted_dates[:10]:
        concept_list = ", ".join(_day_top_concepts(history[day]))
        lines.extend([f"**{day}**: {concept_list}", ""])
    lines += _render_advice(regime)
    return lines


def _turnover_lines(turnover_rows: list[dict]) -> list[str]:
    lines: list[str] = []
    for row in reversed(turnover_rows[-10:]):
        faces = ", ".join(row["new_faces"][:5])
        if len(row["new_faces"]) > 5:
            faces += f" +{len(row['new_faces']) - 5}"
        lines.append(f"| {row['date']} | {row['turnover']:.0%} | {row['new_count']}/{row['total']} | {faces} |")
    return lines


def _day_top_concepts(day_data: dict) -> list[str]:
    sorted_concepts = sorted(day_data.items(), key=lambda item: item[1].get("inflow", 0), reverse=True)[:10]
    return [f"{concept}({info.get('pct', 0):+.1f}%)" for concept, info in sorted_concepts]


def _render_advice(regime: str) -> list[str]:
    lines = ["## 策略建议", ""]
    if regime == "主线延续":
        lines.extend(
            [
                "- 当前板块延续性强，`hot_bonus` 可适当提高（0.03~0.05）以加大主线权重",
                "- 板块强度公式中 q20 权重可维持（长周期因子有效）",
                "- 持仓应偏向主线方向，非热门板块门槛可适当提高",
            ]
        )
    elif regime == "轮动适中":
        lines.extend(["- 板块有一定延续但不极端，当前参数（hot_bonus=0.02）合理", "- 关注 streak≥3 的概念作为核心方向"])
    else:
        lines.extend(
            [
                "- 一日游行情，`hot_bonus` 应降至最低或归零",
                "- 板块强度公式应加大 q3 短期权重，降低 q20",
                "- 非热门板块门槛应放松，避免错过刚启动的板块",
            ]
        )
    lines.append("")
    return lines
