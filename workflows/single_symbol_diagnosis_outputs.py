"""Output rendering for single-symbol funnel diagnosis."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from utils.feishu import send_feishu_notification


def write_single_symbol_outputs(
    output_dir: Path, spec: Any, rows: list[Any], summary: dict[str, Any]
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "csv": output_dir / "daily_diagnostics.csv",
        "json": output_dir / "summary.json",
        "md": output_dir / "report.md",
    }
    _write_csv(paths["csv"], rows)
    paths["json"].write_text(
        json.dumps(_json_payload(spec, rows, summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["md"].write_text(build_single_symbol_report(spec, rows, summary), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def notify_single_symbol_feishu(spec: Any, summary: dict[str, Any], report_path: str) -> None:
    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    send_feishu_notification(
        webhook,
        f"单票漏斗复盘 {spec.symbol}",
        _feishu_content(spec, summary, report_path),
    )


def build_single_symbol_report(spec: Any, rows: list[Any], summary: dict[str, Any]) -> str:
    lines = [
        f"# 单票漏斗复盘诊断：{spec.symbol}",
        "",
        f"- 市场: {spec.label}",
        f"- 回放交易日: {summary['total_days']}",
        f"- 被漏斗选中: {summary['selected_days']}",
        f"- 首次/最后选中: {summary['first_selected'] or '-'} / {summary['last_selected'] or '-'}",
        f"- 层级分布: {_fmt_counts(summary['counts'])}",
        "",
        "> 注：RPS 已基于全市场截面排名（主板+创业板+科创板）；板块热度属于全市场依赖，报告中按单票上下文近似。",
        "",
        "## 每日明细",
        "",
        "| 日期 | 结果 | 卡点 | 触发 | ABC | 收盘 | 涨跌幅 | 量比 | 原因 |",
        "|---|---:|---:|---|---:|---:|---:|---:|---|",
    ]
    lines.extend(_report_row(row) for row in rows)
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()) if rows else ["date"])
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _json_payload(spec: Any, rows: list[Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": asdict(spec),
        "summary": summary,
        "daily": [asdict(row) for row in rows],
        "note": "RPS 已基于全市场截面排名；板块热度无法完全等价于全市场生产任务。",
    }


def _feishu_content(spec: Any, summary: dict[str, Any], report_path: str) -> str:
    run_url = os.getenv("GITHUB_RUN_URL", "").strip()
    return "\n".join(
        [
            f"单票漏斗复盘：{spec.symbol}（{spec.label}）",
            f"- 回放交易日: {summary['total_days']}",
            f"- 被选中: {summary['selected_days']}",
            f"- 首次/最后选中: {summary['first_selected'] or '-'} / {summary['last_selected'] or '-'}",
            f"- 层级分布: {_fmt_counts(summary['counts'])}",
            f"- 报告文件: {report_path}",
            f"- Actions: {run_url or '-'}",
        ]
    )


def _report_row(row: Any) -> str:
    return (
        f"| {row.date} | {row.status} | {row.failed_layer} | {row.triggers} | "
        f"{row.abc_grade} | {_fmt(row.close)} | {_fmt(row.pct_chg, suffix='%')} | "
        f"{_fmt(row.vol_ratio, digits=2, suffix='x')} | {row.reason} |"
    )


def _fmt(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    return "-" if value is None else f"{value:.{digits}f}{suffix}"


def _fmt_counts(counts: dict[str, int]) -> str:
    return " / ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "-"
