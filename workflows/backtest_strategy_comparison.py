"""A/B/C/D/E strategy ablation report from backtest markdown artifacts."""

from __future__ import annotations

import glob
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from workflows.backtest_strategy_variants import VARIANT_LABELS

_DIR_PATTERN = re.compile(
    r"backtest-strategy-(?P<period>recent_2m|recent_6m|bull_2020|bear_2022|custom)-(?P<variant>[A-E])$"
)


@dataclass(frozen=True)
class StrategyComparisonRow:
    period: str
    variant: str
    start: str
    end: str
    cash_return: float | None
    cash_drawdown: float | None
    cash_trades: int | None
    win_rate: float | None
    avg_return: float | None
    sharpe: float | None


def load_strategy_comparison_rows(artifacts_dir: Path) -> list[StrategyComparisonRow]:
    rows: list[StrategyComparisonRow] = []
    paths = sorted(Path(path) for path in glob.glob(str(artifacts_dir / "**" / "summary_*.md"), recursive=True))
    for path in paths:
        match = _DIR_PATTERN.search(path.parent.name)
        if not match:
            continue
        content = path.read_text(encoding="utf-8")
        start, end = _date_range(content)
        rows.append(
            StrategyComparisonRow(
                period=match.group("period"),
                variant=match.group("variant"),
                start=start,
                end=end,
                cash_return=_cash_metric(content, "总收益"),
                cash_drawdown=_cash_metric(content, "现金最大回撤"),
                cash_trades=_cash_int_metric(content, "成交笔数"),
                win_rate=_cash_metric(content, "胜率"),
                avg_return=_metric(content, "平均收益"),
                sharpe=_metric(content, r"夏普比(?:\s*\(Sharpe Ratio\))?"),
            )
        )
    return rows


def build_strategy_comparison(rows: list[StrategyComparisonRow]) -> dict[str, Any]:
    by_variant = _by_variant(rows)
    evaluations = {
        variant: _evaluate_variant(variant, values, by_variant.get("A", [])) for variant, values in by_variant.items()
    }
    return {
        "status": "ready" if {"A", "B", "C", "D", "E"}.issubset(by_variant) else "incomplete",
        "baseline": "A",
        "variant_labels": {key: value for key, value in VARIANT_LABELS.items() if key != "live"},
        "rows": [asdict(row) for row in sorted(rows, key=lambda row: (row.period, row.variant))],
        "evaluations": evaluations,
        "walk_forward": _walk_forward(rows),
        "scope": "B 组验证 Upthrust 当日新开仓 veto；持仓期动态 L5 离场尚未接入本固定退出回放。",
        "decision_rule": "至少两个共同周期、胜出周期过半、平均收益增量为正，且最大回撤恶化不超过2个百分点。",
    }


def render_strategy_comparison(report: dict[str, Any]) -> str:
    lines = [
        "# 策略 A/B/C/D/E 消融对比",
        "",
        "固定同一数据快照、入场、组合与退出参数，仅切换策略能力。A 为基线，B/C/D 为单项，E 为组合。",
        "B 组只验证 Upthrust 当日禁止新开仓；持仓期仍使用统一的固定退出参数，避免把两类效果混在一起。",
        "",
        "| 周期 | 组别 | 现金收益 | 现金回撤 | 成交 | 胜率 | 平均单笔 | 夏普 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(_row_line(row) for row in report.get("rows", []))
    lines.extend(
        [
            "",
            "## 相对 A 组结论",
            "",
            "| 组别 | 共同周期 | 胜出 | 平均收益差 | 最大回撤恶化 | 判定 |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for variant in ("B", "C", "D", "E"):
        item = (report.get("evaluations") or {}).get(variant, {})
        lines.append(
            f"| {variant} | {item.get('common_periods', 0)} | {item.get('wins', 0)} | "
            f"{_fmt(item.get('mean_return_delta'), '%')} | {_fmt(item.get('max_drawdown_worsening'), 'pp')} | "
            f"{item.get('status', 'missing')} |"
        )
    lines.extend(_walk_forward_lines(report.get("walk_forward") or {}))
    return "\n".join(lines) + "\n"


def _by_variant(rows: list[StrategyComparisonRow]) -> dict[str, list[StrategyComparisonRow]]:
    grouped: dict[str, list[StrategyComparisonRow]] = defaultdict(list)
    for row in rows:
        grouped[row.variant].append(row)
    return dict(grouped)


def _evaluate_variant(
    variant: str, rows: list[StrategyComparisonRow], baseline_rows: list[StrategyComparisonRow]
) -> dict[str, Any]:
    if variant == "A":
        return {"status": "baseline", "common_periods": len(rows), "wins": 0}
    baseline = {row.period: row for row in baseline_rows if row.cash_return is not None}
    pairs = [(baseline[row.period], row) for row in rows if row.period in baseline and row.cash_return is not None]
    deltas = [float(row.cash_return) - float(base.cash_return) for base, row in pairs]
    drawdown_worsening = [
        max(abs(float(row.cash_drawdown or 0.0)) - abs(float(base.cash_drawdown or 0.0)), 0.0) for base, row in pairs
    ]
    wins = sum(delta > 0 for delta in deltas)
    required_wins = math.floor(len(pairs) / 2) + 1
    passed = len(pairs) >= 2 and wins >= required_wins and mean(deltas) > 0 and max(drawdown_worsening, default=0) <= 2
    return {
        "status": "pass" if passed else ("review" if len(pairs) >= 2 else "insufficient"),
        "common_periods": len(pairs),
        "wins": wins,
        "mean_return_delta": mean(deltas) if deltas else None,
        "max_drawdown_worsening": max(drawdown_worsening, default=None),
    }


def _walk_forward(rows: list[StrategyComparisonRow]) -> dict[str, Any]:
    grouped: dict[str, list[StrategyComparisonRow]] = defaultdict(list)
    for row in rows:
        if row.cash_return is not None:
            grouped[row.period].append(row)
    periods = sorted(grouped, key=lambda key: max((row.end for row in grouped[key]), default=""))
    windows = []
    for train, test in zip(periods, periods[1:], strict=False):
        selected = max(grouped[train], key=lambda row: float(row.cash_return or float("-inf")))
        test_row = next((row for row in grouped[test] if row.variant == selected.variant), None)
        windows.append(
            {
                "train_period": train,
                "test_period": test,
                "selected_variant": selected.variant,
                "train_return": selected.cash_return,
                "test_return": test_row.cash_return if test_row else None,
            }
        )
    positive = sum(float(row["test_return"]) > 0 for row in windows if row["test_return"] is not None)
    evaluated = sum(row["test_return"] is not None for row in windows)
    return {"status": "pass" if evaluated >= 2 and positive == evaluated else "review", "windows": windows}


def _walk_forward_lines(result: dict[str, Any]) -> list[str]:
    lines = ["", "## Walk-forward", ""]
    for row in result.get("windows", []):
        lines.append(
            f"- {row['train_period']} 选出 {row['selected_variant']}，在 {row['test_period']} 的现金收益为 "
            f"{_fmt(row.get('test_return'), '%')}。"
        )
    lines.append(f"- 判定：{result.get('status', 'review')}。")
    return lines


def _row_line(row: dict[str, Any]) -> str:
    return (
        f"| {row['period']} | {row['variant']} | {_fmt(row.get('cash_return'), '%')} | "
        f"{_fmt(row.get('cash_drawdown'), '%')} | {row.get('cash_trades') or 0} | "
        f"{_fmt(row.get('win_rate'), '%')} | {_fmt(row.get('avg_return'), '%')} | {_fmt(row.get('sharpe'))} |"
    )


def _line_value(content: str, label: str) -> str | None:
    pattern = re.compile(rf"^\s*-\s*{label}\s*:\s*(.+?)\s*$")
    return next((match.group(1) for line in content.splitlines() if (match := pattern.match(line))), None)


def _metric(content: str, label: str) -> float | None:
    raw = _line_value(content, label)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw or "")
    return float(match.group(0)) if match else None


def _cash_section(content: str) -> str:
    marker = "## 真实现金账户模拟"
    if marker not in content:
        return content
    section = content.split(marker, 1)[1]
    return section.split("\n## ", 1)[0]


def _cash_metric(content: str, label: str) -> float | None:
    return _metric(_cash_section(content), label)


def _cash_int_metric(content: str, label: str) -> int | None:
    value = _cash_metric(content, label)
    return int(value) if value is not None else None


def _date_range(content: str) -> tuple[str, str]:
    raw = _line_value(content, "区间") or ""
    parts = [part.strip() for part in raw.split("~", 1)]
    return (parts[0], parts[1]) if len(parts) == 2 else ("", "")


def _fmt(value: object, suffix: str = "") -> str:
    return "-" if value is None else f"{float(value):+.2f}{suffix}"
