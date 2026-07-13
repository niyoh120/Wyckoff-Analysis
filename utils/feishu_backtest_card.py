"""Feishu rich-card elements for backtest summaries."""

from __future__ import annotations

from dataclasses import dataclass

from integrations.tickflow_notice import TICKFLOW_LIMIT_HINT, has_recent_tickflow_limit_event
from utils.feishu_text import lark_md_div, lark_note


@dataclass(frozen=True)
class BacktestCardData:
    win: float | None
    avg: float | None
    sharpe: float | None
    mdd: float | None
    trades: float | None
    hold: str
    sl: str
    tp: str
    trail: str
    bt_range: str
    top_n: str
    pool: str
    track_data: dict
    regime_data: dict


def _extract_number(content: str, keyword: str) -> float | None:
    for line in content.split("\n"):
        if keyword in line:
            val = line.split(":")[-1].strip().rstrip("%")
            try:
                return float(val)
            except ValueError:
                return None
    return None


def _extract_text(content: str, keyword: str) -> str:
    for line in content.split("\n"):
        if keyword in line:
            return line.split(":")[-1].strip()
    return "?"


def _fmt_metric(val: float | None, spec: str) -> str:
    return format(val, spec) if val is not None else "-"


def _parse_vertical_table(content: str, header_keyword: str) -> dict:
    result = {}
    in_table = False
    col_names = []
    for line in content.split("\n"):
        if header_keyword in line and not in_table:
            in_table = True
            continue
        if in_table and line.startswith("| 指标"):
            col_names = [c.strip() for c in line.split("|")[2:-1]]
            for column_name in col_names:
                result[column_name] = {}
            continue
        if in_table and line.startswith("|--"):
            continue
        if in_table and line.startswith("| "):
            parts = [part.strip() for part in line.split("|")[1:-1]]
            if len(parts) >= len(col_names) + 1:
                _fill_table_row(result, col_names, parts)
            continue
        if in_table and (line.startswith("##") or line.strip() == "") and col_names:
            break
    return result


def _fill_table_row(result: dict, col_names: list[str], parts: list[str]) -> None:
    key = parts[0]
    for idx, column_name in enumerate(col_names):
        result[column_name][key] = parts[idx + 1]


def _parse_card_data(content: str) -> BacktestCardData:
    return BacktestCardData(
        win=_extract_number(content, "胜率"),
        avg=_extract_number(content, "平均收益"),
        sharpe=_extract_number(content, "夏普比"),
        mdd=_extract_number(content, "最大回撤"),
        trades=_extract_number(content, "成交样本"),
        hold=_extract_text(content, "持有周期"),
        sl=_extract_text(content, "止损线"),
        tp=_extract_text(content, "止盈线"),
        trail=_extract_text(content, "移动止盈"),
        bt_range=_extract_text(content, "区间"),
        top_n=_extract_text(content, "每日候选上限"),
        pool=_extract_text(content, "股票池"),
        track_data=_parse_vertical_table(content, "Trend vs Accum"),
        regime_data=_parse_vertical_table(content, "按大盘水温"),
    )


def _summary_elements(data: BacktestCardData) -> list[dict]:
    return [
        lark_md_div(f"**区间** {data.bt_range}  ·  **TopN** {data.top_n}  ·  **{data.pool}**"),
        lark_md_div(f"📌 **参数**  持有{data.hold} / SL{data.sl} / TP{data.tp} / 移动止盈{data.trail}"),
        {"tag": "hr"},
    ]


def _core_metric_elements(data: BacktestCardData) -> list[dict]:
    tag = "🏆" if (data.sharpe or 0) > 0 else "📌"
    cols = [
        ("**夏普比**", f"{tag} {_fmt_metric(data.sharpe, '.3f')}"),
        ("**胜率**", f"{_fmt_metric(data.win, '.1f')}%"),
        ("**均收**", f"{_fmt_metric(data.avg, '+.2f')}%"),
        ("**回撤**", f"{_fmt_metric(data.mdd, '.1f')}%"),
        ("**样本**", f"{int(data.trades or 0)}笔"),
    ]
    return [
        {
            "tag": "column_set",
            "flex_mode": "stretch",
            "background_style": "grey",
            "columns": [_metric_column(label, val) for label, val in cols],
        },
        {"tag": "hr"},
    ]


def _metric_column(label: str, value: str) -> dict:
    return {
        "tag": "column",
        "width": "weighted",
        "weight": 1,
        "elements": [lark_md_div(f"{label}\n{value}")],
    }


def _track_elements(track_data: dict) -> list[dict]:
    if not track_data:
        return []
    return [
        lark_md_div("**分轨统计 (Trend vs Accum)**"),
        {"tag": "column_set", "flex_mode": "stretch", "columns": _track_columns(track_data)},
        {"tag": "hr"},
    ]


def _track_columns(track_data: dict) -> list[dict]:
    icons = {"Trend": "⚡", "Accum": "🔄"}
    return [
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [lark_md_div(_track_text(name, data, icons))],
        }
        for name, data in track_data.items()
    ]


def _track_text(name: str, data: dict, icons: dict[str, str]) -> str:
    return (
        f"{icons.get(name, '·')} **{name}**\n"
        f"{data.get('成交笔数', '?')}笔 · 胜率{data.get('胜率(%)', '?')}%\n"
        f"均收{data.get('平均收益(%)', '?')}% · 夏普{data.get('夏普比', '?')}\n"
        f"连亏{data.get('最长连亏', '?')}笔"
    )


def _regime_elements(regime_data: dict) -> list[dict]:
    if not regime_data:
        return []
    return [
        lark_md_div("**按大盘水温**"),
        {"tag": "column_set", "flex_mode": "stretch", "columns": _regime_columns(regime_data)},
    ]


def _regime_columns(regime_data: dict) -> list[dict]:
    regime_icons = {
        "NEUTRAL": "🟡",
        "PANIC_REPAIR": "🟠",
        "PANIC_REPAIR_CONFIRMED": "🟢",
        "RISK_OFF": "🔴",
        "RISK_ON": "🟢",
        "CRASH": "⚫",
    }
    return [
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [lark_md_div(_regime_text(name, data, regime_icons))],
        }
        for name, data in regime_data.items()
    ]


def _regime_text(name: str, data: dict, regime_icons: dict[str, str]) -> str:
    short = name.replace("PANIC_REPAIR", "PANIC")
    return (
        f"{regime_icons.get(name, '·')} **{short}**\n"
        f"{data.get('成交笔数', '?')}笔 · 胜率{data.get('胜率(%)', '?')}%\n"
        f"均收{data.get('平均收益(%)', '?')}%"
    )


def build_backtest_card_elements(content: str) -> tuple[list[dict], str]:
    data = _parse_card_data(content)
    elements = (
        _summary_elements(data)
        + _core_metric_elements(data)
        + _track_elements(data.track_data)
        + _regime_elements(data.regime_data)
    )
    if has_recent_tickflow_limit_event():
        elements.append({"tag": "hr"})
        elements.append(lark_note(f"⚠️ {TICKFLOW_LIMIT_HINT}"))
    template = "blue" if (data.sharpe or 0) > 0 else "orange"
    return elements, template
