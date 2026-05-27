"""Run the strategic theme radar and write a markdown report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

if __name__ == "__main__" or not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.theme_radar import build_theme_radar_snapshot
from integrations.data_source import _CONCEPT_HEAT_HISTORY
from integrations.supabase_concept_heat import load_concept_heat_history_from_supabase
from integrations.theme_radar_storage import persist_theme_radar_snapshot
from scripts.wyckoff_funnel import run_funnel_job

STATE_LABELS = {
    "observe": "萌芽观察",
    "confirmed": "主线确认",
    "extension": "趋势延续",
    "overheated": "过热拥挤",
    "decay": "噪音/衰退",
}


def main() -> None:
    args = _parse_args()
    snapshot = run_theme_radar(with_news=args.with_news, persist=not args.no_persist)
    report = render_theme_radar_report(snapshot)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[theme_radar] report: {output}")
    print(report)


def run_theme_radar(*, with_news: bool = False, persist: bool = True) -> dict:
    events = _collect_events(with_news)
    _triggers, metrics = run_funnel_job(include_debug_context=True)
    debug = metrics.get("_debug", {}) or {}
    snapshot = build_theme_radar_snapshot(
        trade_date=str(metrics.get("end_trade_date") or date.today().isoformat()),
        concept_heat=metrics.get("concept_heat_full") or metrics.get("concept_heat", []) or [],
        concept_history=_load_concept_history(),
        concept_map=debug.get("concept_map", {}) or {},
        sector_map=debug.get("sector_map", {}) or {},
        df_map=metrics.get("all_df_map", {}) or {},
        events=events,
        name_map=debug.get("name_map", {}) or {},
    )
    if persist:
        result = persist_theme_radar_snapshot(snapshot)
        print(f"[theme_radar] persist: supabase={result.get('supabase', 0)}, sqlite={result.get('sqlite', 0)}")
    return snapshot


def render_theme_radar_report(snapshot: dict) -> str:
    lines = [
        "# Theme Radar",
        "",
        f"**交易日**: {snapshot.get('trade_date', '')}",
        "",
        "## 主线评分",
        "",
    ]
    lines.extend(_theme_table(snapshot.get("themes", []) or []))
    lines.extend(["", "## 战略观察池", ""])
    lines.extend(_candidate_table(snapshot.get("strategic_candidates", []) or []))
    lines.extend(["", "## 证据", ""])
    lines.extend(_evidence_lines(snapshot.get("themes", []) or []))
    return "\n".join(lines)


def _theme_table(themes: list[dict]) -> list[str]:
    if not themes:
        return ["暂无分数超过阈值的中长线主题。"]
    lines = [
        "| 主题 | 状态 | 总分 | 热度 | 结构 | 宽度 | 持续 | 催化 | 拥挤 | 成分数 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in themes:
        lines.append(
            f"| {item['theme']} | {STATE_LABELS.get(item['state'], item['state'])} | "
            f"{item['score']:.2f} | {item['heat_score']:.2f} | {item['structure_score']:.2f} | "
            f"{item['breadth_score']:.2f} | {item['persistence_score']:.2f} | "
            f"{item['catalyst_score']:.2f} | {item['crowding_score']:.2f} | {item['member_count']} |"
        )
    return lines


def _candidate_table(candidates: list[dict]) -> list[str]:
    if not candidates:
        return ["暂无战略候选，说明主题强度或个股结构还不够。"]
    lines = ["| 代码 | 名称 | 主题 | 状态 | 股票分 | 主题分 | 理由 |", "|---|---|---|---:|---:|---:|---|"]
    for item in candidates[:40]:
        reasons = "; ".join(item.get("reasons", [])[:3])
        lines.append(
            f"| {item['code']} | {item['name']} | {item['theme']} | "
            f"{STATE_LABELS.get(item['state'], item['state'])} | {item['stock_score']:.2f} | "
            f"{item['theme_score']:.2f} | {reasons} |"
        )
    return lines


def _evidence_lines(themes: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in themes[:10]:
        evidence = item.get("evidence", []) or ["无"]
        lines.append(f"- **{item['theme']}**: {'; '.join(evidence)}")
    return lines or ["暂无证据。"]


def _collect_events(with_news: bool) -> list[dict]:
    if not with_news:
        return []
    from integrations.theme_news import collect_theme_events

    return collect_theme_events()


def _load_concept_history() -> dict:
    history = load_concept_heat_history_from_supabase()
    if history:
        return history
    if not _CONCEPT_HEAT_HISTORY.exists():
        return {}
    with open(_CONCEPT_HEAT_HISTORY, encoding="utf-8") as f:
        return json.load(f)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run strategic theme radar")
    parser.add_argument("--with-news", action="store_true", help="collect optional public news/GDELT events")
    parser.add_argument("--no-persist", action="store_true", help="skip local SQLite snapshot persistence")
    parser.add_argument("--output", default="logs/theme_radar_report.md", help="markdown output path")
    return parser.parse_args()


if __name__ == "__main__":
    main()
