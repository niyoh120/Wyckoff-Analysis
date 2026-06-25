"""Report rendering and artifact writing for HK/US market funnel jobs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.candidate_ranker import TRIGGER_LABELS


def market_funnel_report_path(output_path: Path | None) -> Path | None:
    if output_path is None:
        return None
    if output_path.name.endswith("_result.json"):
        return output_path.with_name(output_path.name.replace("_result.json", "_report.md"))
    return output_path.with_suffix(".md")


def render_market_funnel_report(result: dict[str, Any]) -> str:
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    candidates = result.get("top_candidates") if isinstance(result.get("top_candidates"), list) else []
    blocks = [
        f"# Wyckoff Funnel {result.get('label', result.get('market', ''))} 最终报告",
        *_overview_block(result, metrics),
        *_trigger_block(metrics),
        *_candidate_block(candidates),
        *_trend_watch_block(metrics),
        *_runtime_block(result),
    ]
    return "\n".join(blocks).rstrip() + "\n"


def write_market_funnel_output(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[market-funnel] result written: {path}")


def write_market_funnel_report(path: Path | None, result: dict[str, Any]) -> None:
    report = render_market_funnel_report(result)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"[market-funnel] report written: {path}")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as fh:
            fh.write(report + "\n")


def _overview_block(result: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    rows = [
        ("股票池", result.get("universe_symbol_count")),
        ("实时行情返回", result.get("quote_count")),
        ("流动性预筛", result.get("selected_count")),
        ("日K可用", result.get("fetched_count")),
        ("L1 基础结构", metrics.get("layer1")),
        ("L2 强弱通道", metrics.get("layer2")),
        ("L3 板块共振", metrics.get("layer3")),
        ("L4 触发命中", metrics.get("total_hits")),
    ]
    return [
        "## 漏斗概览",
        "| 阶段 | 数量 |",
        "| --- | ---: |",
        *[f"| {name} | {_fmt_number(value)} |" for name, value in rows],
        "",
    ]


def _trigger_block(metrics: dict[str, Any]) -> list[str]:
    rows = [
        f"| {TRIGGER_LABELS.get(str(key), str(key))} | {_fmt_number(count)} |"
        for key, count in (metrics.get("by_trigger") or {}).items()
    ]
    return [
        "## 触发分布",
        "| 触发 | 数量 |",
        "| --- | ---: |",
        *(rows or ["| 无触发 | 0 |"]),
        "",
    ]


def _candidate_block(candidates: list[dict[str, Any]]) -> list[str]:
    rows = []
    for index, item in enumerate(candidates[:30], start=1):
        triggers = " / ".join(str(x) for x in item.get("triggers", [])) or "-"
        rows.append(
            "| "
            f"{index} | {item.get('symbol', '-')} | {item.get('name', '-')} | "
            f"{_fmt_float(item.get('score'))} | {_fmt_float(item.get('latest_close'), 3)} | {triggers} |"
        )
    return [
        "## Top 候选",
        "| # | 代码 | 名称 | 分数 | 最新收盘 | 触发 |",
        "| ---: | --- | --- | ---: | ---: | --- |",
        *(rows or ["| - | - | - | - | - | 本次无 L4 触发候选 |"]),
        "",
    ]


def _trend_watch_block(metrics: dict[str, Any]) -> list[str]:
    rows = []
    trend_rows = metrics.get("trend_watch_rows") or metrics.get("leader_radar_rows") or []
    for index, item in enumerate(trend_rows[:10], start=1):
        rows.append(
            "| "
            f"{index} | {item.get('code', '-')} | {_fmt_float(item.get('score'))} | "
            f"{_fmt_float(item.get('ret20'))}% | {_fmt_float(item.get('ret60'))}% | "
            f"{_fmt_float(item.get('ret120'))}% | {item.get('risk', '-')} |"
        )
    return [
        "## 趋势观察池",
        "仅观察强趋势背景，不是买入信号；进入正式推荐仍必须通过候选车道和尾盘确认。",
        "| # | 代码 | 分数 | 20日 | 60日 | 120日 | 风险 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- |",
        *(rows or ["| - | - | - | - | - | - | 本次无趋势观察候选 |"]),
        "",
    ]


def _runtime_block(result: dict[str, Any]) -> list[str]:
    limits = result.get("limits", {})
    return [
        "## 运行参数",
        f"- 股票池文件: `{result.get('symbol_file', '-')}`",
        f"- 实时行情: `{limits.get('quote_batch_size', '-')}` 标的/批, sleep `{limits.get('quote_batch_sleep', '-')}`s",
        f"- 日K批量: `{limits.get('kline_batch_size', '-')}` 标的/批, sleep `{limits.get('kline_batch_sleep', '-')}`s",
        f"- 成交额门槛: `{_fmt_number(limits.get('min_quote_amount'))}`",
    ]


def _fmt_number(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_float(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"
