"""板块延续性报告：评估最近概念板块的强弱与延续性。"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.data_source import _CONCEPT_HEAT_HISTORY, fetch_concept_heat
from integrations.supabase_concept_heat import load_concept_heat_history_from_supabase, upsert_concept_heat_history


def _load_history() -> dict[str, dict]:
    history = load_concept_heat_history_from_supabase()
    if history:
        print(f"[sector_continuity] Supabase 历史覆盖 {len(history)} 个交易日")
        return history
    if not _CONCEPT_HEAT_HISTORY.exists():
        return {}
    with open(_CONCEPT_HEAT_HISTORY, encoding="utf-8") as f:
        return json.load(f)


def _update_history_with_today(history: dict, heat: list[dict]) -> dict:
    """将今日热度写入 history（不落盘，仅内存）。"""
    today = date.today().isoformat()
    top_items = sorted(heat, key=lambda x: x.get("net_inflow", 0), reverse=True)[:20]
    history[today] = {
        it["name"]: {"pct": it.get("pct", 0.0), "inflow": it.get("net_inflow", 0)} for it in top_items if it.get("name")
    }
    sorted_dates = sorted(history.keys(), reverse=True)[:20]
    return {d: history[d] for d in sorted_dates}


def _compute_streaks(history: dict) -> dict[str, int]:
    """计算每个概念从最新日期往回的连续出现天数。"""
    sorted_dates = sorted(history.keys(), reverse=True)
    if not sorted_dates:
        return {}
    latest_concepts = set(history[sorted_dates[0]].keys())
    streaks: dict[str, int] = {}
    for concept in latest_concepts:
        streak = 1
        for d in sorted_dates[1:]:
            if concept in history.get(d, {}):
                streak += 1
            else:
                break
        streaks[concept] = streak
    return dict(sorted(streaks.items(), key=lambda x: -x[1]))


def _compute_daily_turnover(history: dict) -> list[dict]:
    """计算每天 Top-N 的换手率（相对前一天的新面孔比例）。"""
    sorted_dates = sorted(history.keys())
    rows = []
    for i in range(1, len(sorted_dates)):
        prev_set = set(history[sorted_dates[i - 1]].keys())
        curr_set = set(history[sorted_dates[i]].keys())
        if not curr_set:
            continue
        new_faces = curr_set - prev_set
        turnover = len(new_faces) / len(curr_set)
        rows.append(
            {
                "date": sorted_dates[i],
                "turnover": turnover,
                "new_count": len(new_faces),
                "total": len(curr_set),
                "new_faces": sorted(new_faces),
            }
        )
    return rows


def _classify_regime(avg_streak: float, avg_turnover: float) -> str:
    if avg_streak >= 4 and avg_turnover < 0.3:
        return "主线延续"
    elif avg_streak >= 2.5 or avg_turnover < 0.45:
        return "轮动适中"
    else:
        return "一日游"


def _render_summary(
    sorted_dates: list[str], regime: str, avg_streak: float, avg_turnover: float, streaks: dict
) -> list[str]:
    lines: list[str] = [
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
        f"| 连续 ≥3 天的主线概念数 | {sum(1 for s in streaks.values() if s >= 3)} |",
        f"| 连续 ≥5 天的超强主线数 | {sum(1 for s in streaks.values() if s >= 5)} |",
        "",
    ]
    return lines


def _render_theme_lines(history: dict, sorted_dates: list[str], streaks: dict) -> list[str]:
    top_streaks = [(c, s) for c, s in streaks.items() if s >= 2]
    lines = ["## 当前主线（连续 ≥2 天）", ""]
    if not top_streaks:
        lines.append("*无连续 ≥2 天的概念，纯一日游行情*")
        lines.append("")
        return lines
    lines.append("| 概念 | 连续天数 | 今日涨幅 | 今日资金净流入 |")
    lines.append("|------|---------|---------|--------------|")
    today_data = history.get(sorted_dates[0], {})
    for concept, streak in top_streaks:
        info = today_data.get(concept, {})
        pct = info.get("pct", 0.0)
        inflow = info.get("inflow", 0)
        inflow_yi = inflow / 1e8 if abs(inflow) > 1e6 else inflow / 1e4
        unit = "亿" if abs(inflow) > 1e6 else "万"
        lines.append(f"| {concept} | {streak} | {pct:+.2f}% | {inflow_yi:.1f}{unit} |")
    lines.append("")
    return lines


def _render_details(history: dict, sorted_dates: list[str], turnover_rows: list[dict], regime: str) -> list[str]:
    lines = ["## 每日轮动速率", "", "| 日期 | 换手率 | 新面孔数 | 新进概念 |", "|------|--------|---------|---------|"]
    for r in reversed(turnover_rows[-10:]):
        faces = ", ".join(r["new_faces"][:5])
        if len(r["new_faces"]) > 5:
            faces += f" +{len(r['new_faces']) - 5}"
        lines.append(f"| {r['date']} | {r['turnover']:.0%} | {r['new_count']}/{r['total']} | {faces} |")
    lines.append("")
    lines.append("## 每日 Top-10 概念")
    lines.append("")
    for d in sorted_dates[:10]:
        day_data = history[d]
        sorted_concepts = sorted(day_data.items(), key=lambda x: x[1].get("inflow", 0), reverse=True)[:10]
        concept_list = ", ".join(f"{c}({info.get('pct', 0):+.1f}%)" for c, info in sorted_concepts)
        lines.append(f"**{d}**: {concept_list}")
        lines.append("")
    lines += _render_advice(regime)
    return lines


def _render_advice(regime: str) -> list[str]:
    lines = ["## 策略建议", ""]
    if regime == "主线延续":
        lines.append("- 当前板块延续性强，`hot_bonus` 可适当提高（0.03~0.05）以加大主线权重")
        lines.append("- 板块强度公式中 q20 权重可维持（长周期因子有效）")
        lines.append("- 持仓应偏向主线方向，非热门板块门槛可适当提高")
    elif regime == "轮动适中":
        lines.append("- 板块有一定延续但不极端，当前参数（hot_bonus=0.02）合理")
        lines.append("- 关注 streak≥3 的概念作为核心方向")
    else:
        lines.append("- 一日游行情，`hot_bonus` 应降至最低或归零")
        lines.append("- 板块强度公式应加大 q3 短期权重，降低 q20")
        lines.append("- 非热门板块门槛应放松，避免错过刚启动的板块")
    lines.append("")
    return lines


def _build_report(history: dict, heat_today: list[dict]) -> str:
    sorted_dates = sorted(history.keys(), reverse=True)
    streaks = _compute_streaks(history)
    turnover_rows = _compute_daily_turnover(history)

    avg_streak = sum(streaks.values()) / len(streaks) if streaks else 0
    avg_turnover = sum(r["turnover"] for r in turnover_rows) / len(turnover_rows) if turnover_rows else 1.0
    regime = _classify_regime(avg_streak, avg_turnover)

    lines = _render_summary(sorted_dates, regime, avg_streak, avg_turnover, streaks)
    lines += _render_theme_lines(history, sorted_dates, streaks)
    lines += _render_details(history, sorted_dates, turnover_rows, regime)
    return "\n".join(lines)


def main() -> None:
    print("[sector_continuity] 加载概念热度...")
    heat = fetch_concept_heat()
    history = _load_history()

    if heat:
        written = upsert_concept_heat_history(date.today().isoformat(), heat)
        if written:
            print(f"[sector_continuity] Supabase 写入今日概念热度 {written} 条")
        history = _update_history_with_today(history, heat)

    if not history:
        print("❌ 无历史数据，请确保已运行过漏斗或手动积累 concept_heat_history.json")
        sys.exit(1)

    print(f"[sector_continuity] 历史覆盖 {len(history)} 个交易日")
    report = _build_report(history, heat)

    out_dir = Path("logs")
    out_dir.mkdir(exist_ok=True)
    report_path = out_dir / "sector_continuity_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"[sector_continuity] 报告已生成: {report_path}")
    print(report)


if __name__ == "__main__":
    main()
