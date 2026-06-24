"""Build the persistent market-cycle backtest report from grid artifacts."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime
from statistics import mean, median

from core.backtest_grid_ranking import (
    RobustParamScore,
    rank_robust_params,
    robust_label,
    weak_period_guardrails,
)
from workflows.backtest_market_report_artifacts import GridCell, read_trades

REGIME_LABELS = {
    "CRASH": "下跌/踩踏期",
    "PANIC_REPAIR": "恐慌修复期",
    "RISK_OFF": "防守/风险偏好收缩期",
    "NEUTRAL": "震荡中性期",
    "RISK_ON": "风险偏好扩张期",
    "BEAR_REBOUND": "熊市反抽期",
}

PERIOD_LABELS = {
    "recent_6m": "最近6个月",
    "bull_2020": "牛市 2020-07~2021-02",
    "bear_2022": "熊市 2021-12~2022-10",
    "custom": "自定义周期",
}

PERIOD_ORDER = {"recent_6m": 0, "bull_2020": 1, "bear_2022": 2, "custom": 3}
STYLE_ORDER = {
    "slot_equal_4": 0,
    "probe_add": 1,
    "confirmation_only": 2,
    "trend_pyramid": 3,
    "concentrated_swap": 4,
}


def _safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _safe_median(values: list[float]) -> float | None:
    return median(values) if values else None


def _pct(num: int, den: int) -> float | None:
    return num / den * 100.0 if den else None


def _fmt_num(value: float | int | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "-"
    return f"{value:.{digits}f}{suffix}"


def _fmt_signed(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:+.{digits}f}{suffix}"


def _cash_pnl(cell: GridCell) -> float | None:
    if cell.cash_initial is None or cell.cash_final is None:
        return None
    return cell.cash_final - cell.cash_initial


def _fmt_param(cell: GridCell) -> str:
    sl = "无SL" if cell.stop_loss == 0 else f"SL-{cell.stop_loss}%"
    tp = f"TP{cell.take_profit}%" if cell.take_profit else "无TP"
    tr = f"Trail-{cell.trailing_stop}%" if cell.trailing_stop else "无Trail"
    style = cell.portfolio_style_label or cell.portfolio_style
    return f"{style} / {cell.hold}天 / {sl} / {tp} / {tr}"


def _period_label(cell: GridCell) -> str:
    if cell.period_key:
        return PERIOD_LABELS.get(cell.period_key, cell.period_key)
    return f"{cell.start} ~ {cell.end}" if cell.start or cell.end else "未标记周期"


def _period_sort_key(label: str) -> tuple[int, str]:
    return PERIOD_ORDER.get(label, 99), label


def _style_sort_key(label: str) -> tuple[int, str]:
    return STYLE_ORDER.get(label, 99), label


def _format_backtest_ranges(cells: list[GridCell]) -> str:
    groups: dict[str, list[GridCell]] = defaultdict(list)
    for cell in cells:
        groups[cell.period_key or _period_label(cell)].append(cell)
    if len(groups) == 1:
        group = next(iter(groups.values()))
        starts = [c.start for c in group if c.start]
        ends = [c.end for c in group if c.end]
        return f"{min(starts, default='-')} ~ {max(ends, default='-')}"

    parts = []
    for key in sorted(groups, key=_period_sort_key):
        group = groups[key]
        starts = [c.start for c in group if c.start]
        ends = [c.end for c in group if c.end]
        label = PERIOD_LABELS.get(key, key)
        parts.append(f"{label}: {min(starts, default='-')} ~ {max(ends, default='-')} ({len(group)}组)")
    return "；".join(parts)


def _cell_sort_key(cell: GridCell) -> float:
    return cell.sharpe if cell.sharpe is not None else float("-inf")


def _cash_sort_key(cell: GridCell) -> float:
    if cell.cash_total_return is not None:
        return cell.cash_total_return
    return _cell_sort_key(cell)


def _cash_drawdown(cell: GridCell) -> float | None:
    return cell.cash_max_drawdown if cell.cash_max_drawdown is not None else cell.max_drawdown


def _robust_param_key(cell: GridCell) -> tuple[str, int, int, int, int]:
    return (cell.portfolio_style or "slot_equal_4", cell.hold, cell.stop_loss, cell.take_profit, cell.trailing_stop)


def _cell_cash_return(cell: GridCell) -> float:
    return cell.cash_total_return if cell.cash_total_return is not None else float("-inf")


def _cell_cash_return_or_none(cell: GridCell) -> float | None:
    value = _cell_cash_return(cell)
    return None if value == float("-inf") else value


def _representative_cell(cells: list[GridCell]) -> GridCell:
    recent = [c for c in cells if c.period_key == "recent_6m"]
    pool = recent or cells
    return max(pool, key=_cash_sort_key)


def _robust_label(score: RobustParamScore | None) -> str:
    return robust_label(score)


def _rank_robust_params(cells: list[GridCell]) -> list[RobustParamScore]:
    return rank_robust_params(
        cells,
        key_fn=_robust_param_key,
        period_fn=lambda cell: cell.period_key or _period_label(cell),
        value_fn=_cell_cash_return_or_none,
        representative_fn=_representative_cell,
    )


def _build_period_best_table(cells: list[GridCell]) -> list[str]:
    groups: dict[str, list[GridCell]] = defaultdict(list)
    for cell in cells:
        groups[cell.period_key or _period_label(cell)].append(cell)
    if len(groups) < 2:
        return []

    lines = [
        "",
        "## 各周期最佳",
        "",
        "| 周期 | 区间 | 最佳参数 | 现金收益 | 最终现金 | 夏普 | 现金回撤 | 单元 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for key in sorted(groups, key=_period_sort_key):
        group = groups[key]
        best = max(group, key=_cash_sort_key)
        starts = [c.start for c in group if c.start]
        ends = [c.end for c in group if c.end]
        lines.append(
            "| "
            + " | ".join(
                [
                    PERIOD_LABELS.get(key, key),
                    f"{min(starts, default='-')} ~ {max(ends, default='-')}",
                    _fmt_param(best),
                    _fmt_signed(best.cash_total_return, 2, "%"),
                    _fmt_num(best.cash_final, 2),
                    _fmt_num(best.sharpe, 3),
                    _fmt_num(_cash_drawdown(best), 1, "%"),
                    str(len(group)),
                ]
            )
            + " |"
        )
    return lines


def _build_style_best_table(cells: list[GridCell]) -> list[str]:
    groups: dict[str, list[GridCell]] = defaultdict(list)
    for cell in cells:
        groups[cell.portfolio_style or "slot_equal_4"].append(cell)
    if len(groups) < 2:
        return []

    lines = [
        "",
        "## 各交易风格最佳",
        "",
        "| 风格 | 最佳周期 | 最佳参数 | 现金收益 | 最终现金 | 夏普 | 现金回撤 | 单元 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for key in sorted(groups, key=_style_sort_key):
        group = groups[key]
        best = max(group, key=_cash_sort_key)
        lines.append(
            "| "
            + " | ".join(
                [
                    best.portfolio_style_label or key,
                    PERIOD_LABELS.get(best.period_key, best.period_key or "-"),
                    _fmt_param(best),
                    _fmt_signed(best.cash_total_return, 2, "%"),
                    _fmt_num(best.cash_final, 2),
                    _fmt_num(best.sharpe, 3),
                    _fmt_num(_cash_drawdown(best), 1, "%"),
                    str(len(group)),
                ]
            )
            + " |"
        )
    return lines


def _build_robust_param_table(scores: list[RobustParamScore]) -> list[str]:
    if len(scores) < 2:
        return []
    lines = [
        "",
        "## 跨周期参数稳健性",
        "",
        "| 排名 | 参数组合 | 正周期 | 最近收益 | 平均收益 | 最差收益 | 稳健分 | 覆盖周期 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, score in enumerate(scores[:12], 1):
        cell = score.best_cell
        marker = " 🏆" if idx == 1 else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    f"{_fmt_param(cell)}{marker}",
                    f"{score.positive_periods}/{score.period_count}",
                    _fmt_signed(score.recent_cash_return, 2, "%"),
                    _fmt_signed(score.avg_cash_return, 2, "%"),
                    _fmt_signed(score.min_cash_return, 2, "%"),
                    _fmt_num(score.score, 2),
                    str(score.period_count),
                ]
            )
            + " |"
        )
    return lines


def _build_matrix(cells: list[GridCell], best: GridCell) -> list[str]:
    holds = sorted({c.hold for c in cells})
    stops = sorted({c.stop_loss for c in cells})
    by_pair: dict[tuple[int, int], GridCell] = {}
    for c in cells:
        key = (c.hold, c.stop_loss)
        if key not in by_pair or _cell_sort_key(c) > _cell_sort_key(by_pair[key]):
            by_pair[key] = c

    lines = []
    lines.append("| 持有\\SL | " + " | ".join("无SL" if s == 0 else f"-{s}%" for s in stops) + " |")
    lines.append("|---|" + "|".join(["---:"] * len(stops)) + "|")
    for h in holds:
        row = [f"{h}天"]
        for s in stops:
            c = by_pair.get((h, s))
            if not c or c.sharpe is None:
                row.append("-")
            else:
                marker = " 🏆" if c == best else ""
                row.append(f"{c.sharpe:.3f}{marker}")
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _numeric_ret(row: dict[str, str]) -> float | None:
    try:
        return float(row.get("ret_pct", ""))
    except ValueError:
        return None


def _group_stats(rows: list[dict[str, str]], key_fn: Callable[[dict[str, str]], str]) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row) or "-"].append(row)

    stats: list[dict[str, object]] = []
    for key, items in groups.items():
        returns = [v for r in items if (v := _numeric_ret(r)) is not None]
        wins = sum(1 for v in returns if v > 0)
        dates = sorted({r.get("signal_date", "") for r in items if r.get("signal_date")})
        stats.append(
            {
                "key": key,
                "count": len(returns),
                "win_rate": _pct(wins, len(returns)),
                "avg": _safe_mean(returns),
                "median": _safe_median(returns),
                "first_date": dates[0] if dates else "",
                "last_date": dates[-1] if dates else "",
            }
        )
    return sorted(stats, key=lambda x: (-int(x["count"]), str(x["key"])))


def _latest_cycle(rows: list[dict[str, str]], sample_size: int = 20) -> tuple[str, str]:
    dated = [r for r in rows if r.get("signal_date")]
    dated.sort(key=lambda r: (r.get("signal_date", ""), r.get("code", "")))
    tail = dated[-sample_size:]
    if not tail:
        return "样本不足", "未找到可完整验证的尾段交易样本。"

    counts = Counter(r.get("regime", "-") or "-" for r in tail)
    dominant = counts.most_common(2)
    latest_date = tail[-1].get("signal_date", "")
    first_date = tail[0].get("signal_date", "")
    label_parts = [f"{k}({REGIME_LABELS.get(k, k)}) {v}/{len(tail)}" for k, v in dominant]
    cycle = f"{dominant[0][0]} / {dominant[1][0]} 切换观察期" if len(dominant) >= 2 else f"{dominant[0][0]} 主导期"
    detail = (
        f"最优组合可完整验证的尾段信号为 {first_date} ~ {latest_date}，近 {len(tail)} 笔以 "
        + "、".join(label_parts)
        + " 为主。"
    )
    return cycle, detail


def _build_trade_diagnostics(rows: list[dict[str, str]]) -> dict[str, object]:
    returns = [v for r in rows if (v := _numeric_ret(r)) is not None]
    wins = [v for v in returns if v > 0]
    losses = [v for v in returns if v <= 0]
    sorted_desc = sorted(returns, reverse=True)
    drop_top_1 = _safe_mean(sorted_desc[1:]) if len(sorted_desc) > 1 else None
    drop_top_3 = _safe_mean(sorted_desc[3:]) if len(sorted_desc) > 3 else None
    payoff = None
    if wins and losses:
        avg_loss = abs(mean(losses))
        payoff = mean(wins) / avg_loss if avg_loss > 0 else None
    dates = sorted({r.get("signal_date", "") for r in rows if r.get("signal_date")})
    return {
        "count": len(returns),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _pct(len(wins), len(returns)),
        "avg_win": _safe_mean(wins),
        "avg_loss": _safe_mean(losses),
        "payoff": payoff,
        "avg_all": _safe_mean(returns),
        "median_all": _safe_median(returns),
        "drop_top_1_avg": drop_top_1,
        "drop_top_3_avg": drop_top_3,
        "first_signal_date": dates[0] if dates else "",
        "last_signal_date": dates[-1] if dates else "",
    }


def _best_per_hold_comment(cells: list[GridCell]) -> str:
    parts = []
    for hold in sorted({c.hold for c in cells}):
        subset = [c for c in cells if c.hold == hold and c.sharpe is not None]
        if not subset:
            continue
        best = max(subset, key=_cell_sort_key)
        parts.append(f"{hold}天最佳 {_fmt_param(best)}，夏普 {best.sharpe:.3f}")
    return "；".join(parts)


def _build_execution_context_lines(
    *,
    cells: list[GridCell],
    best: GridCell,
    diagnostics: dict[str, object],
    current_cycle: str,
    cycle_detail: str,
    generated: str,
    pos_sharpe: int,
    neg_sharpe: int,
    run_url: str,
) -> list[str]:
    return [
        "# 当前市场回测报告",
        "",
        f"> 自动生成于 {generated}。本文件由 `scripts/update_backtest_market_report.py` 从 Backtest Grid artifacts 更新。",
        "",
        "## 执行上下文",
        "",
        "- 回测脚本: `python -m scripts.backtest_runner`（由 `.github/workflows/backtest_grid.yml` 手动触发精简参数网格并发执行）",
        f"- 回测区间: {_format_backtest_ranges(cells)}",
        f"- 市场周期: {current_cycle}",
        f"- 周期说明: {cycle_detail}",
        f"- 可完整验证信号期: {diagnostics.get('first_signal_date') or '-'} ~ {diagnostics.get('last_signal_date') or '-'}",
        f"- 股票池: {best.board or '-'} (sample={best.sample_size or '-'})",
        f"- 每日候选上限: {best.top_n or '-'}",
        f"- 参数/风格单元: {len(cells)} 组；正夏普 {pos_sharpe} 组，非正夏普 {neg_sharpe} 组",
        f"- GitHub Actions: {run_url or '-'}",
    ]


def _build_conclusion_lines(
    *,
    cells: list[GridCell],
    best: GridCell,
    robust_best: RobustParamScore | None,
    diagnostics: dict[str, object],
) -> list[str]:
    lines = [
        "",
        "## 本次结论",
        "",
        f"- {_robust_label(robust_best)}: **{_fmt_param(best)}**",
        f"- 代表单元: 夏普 **{_fmt_num(best.sharpe, 3)}**；胜率 **{_fmt_num(best.win_rate, 1, '%')}**；单笔均收 **{_fmt_signed(best.avg_ret, 2, '%')}**；最大回撤 **{_fmt_num(best.max_drawdown, 1, '%')}**；样本 **{best.trades or 0}** 笔",
        f"- 代表现金账户: 初始 **{_fmt_num(best.cash_initial, 2)}**；最终 **{_fmt_num(best.cash_final, 2)}**；盈亏 **{_fmt_signed(_cash_pnl(best), 2)}**；收益 **{_fmt_signed(best.cash_total_return, 2, '%')}**；现金回撤 **{_fmt_num(_cash_drawdown(best), 1, '%')}**；现金成交 **{best.cash_trades or 0}** 笔",
        f"- wbt 校验: 夏普 {_fmt_num(best.wbt_sharpe, 3)}，最大回撤 {_fmt_num(best.wbt_max_drawdown, 2, '%')}，日胜率 {_fmt_num(best.wbt_daily_win_rate, 2, '%')}；绩效引擎 `{best.metrics_engine or '-'}`",
        f"- 参数观察: {_best_per_hold_comment(cells)}",
    ]
    if robust_best:
        lines.append(
            f"- 跨周期稳健性: 正收益周期 {robust_best.positive_periods}/{robust_best.period_count}；"
            f"平均现金收益 {_fmt_signed(robust_best.avg_cash_return, 2, '%')}；"
            f"最差周期 {_fmt_signed(robust_best.min_cash_return, 2, '%')}；"
            f"稳健分 {_fmt_num(robust_best.score, 2)}。"
        )
    lines.extend(_build_period_guardrail_lines(cells))
    if best.take_profit == 0:
        lines.append("- 退出观察: 当前最佳组合关闭固定止盈，说明右尾大赢家对收益贡献很大，固定 TP 容易截断趋势。")
    if best.win_rate is not None and best.win_rate < 35 and best.avg_ret is not None and best.avg_ret > 0:
        lines.append(
            "- 胜率结构: 单笔胜率偏低但均收为正，属于低胜率/高赔率的趋势跟踪形态；需要监控右尾依赖，而不是单纯追求高胜率。"
        )
    if diagnostics.get("drop_top_1_avg") is not None and best.avg_ret is not None:
        lines.append(
            f"- 右尾依赖: 去掉最大盈利单后单笔均收约 {_fmt_signed(diagnostics['drop_top_1_avg'], 2, '%')}；"
            f"去掉前三大盈利单后约 {_fmt_signed(diagnostics['drop_top_3_avg'], 2, '%')}。"
        )
    return lines


def _build_period_guardrail_lines(cells: list[GridCell]) -> list[str]:
    lines = []
    for guard in weak_period_guardrails(
        cells,
        period_fn=lambda cell: cell.period_key or _period_label(cell),
        value_fn=_cell_cash_return_or_none,
    ):
        label = PERIOD_LABELS.get(guard.period_key, guard.period_key)
        lines.append(
            f"- 周期风控: **{label}** 全部组合非正，最佳现金收益 {_fmt_signed(guard.best_value, 2, '%')}；建议默认空仓/影子观察。"
        )
    return lines


def _build_followup_lines(regime_stats: list[dict[str, object]], trigger_stats: list[dict[str, object]]) -> list[str]:
    negative_regimes = [s for s in regime_stats if isinstance(s["avg"], float) and s["avg"] < 0]
    positive_regimes = [s for s in regime_stats if isinstance(s["avg"], float) and s["avg"] > 0]
    lines = ["", "## 解读与后续策略", ""]
    if positive_regimes:
        pos_text = "、".join(f"{s['key']}({_fmt_signed(s['avg'], 2, '%')})" for s in positive_regimes)
        lines.append(f"- 优势周期: {pos_text}，这些水温下更适合保留趋势跟踪仓位。")
    if negative_regimes:
        neg_text = "、".join(f"{s['key']}({_fmt_signed(s['avg'], 2, '%')})" for s in negative_regimes)
        lines.append(f"- 弱势周期: {neg_text}，这些水温下建议降仓、禁开或增加确认。")
    pure_sos = next((s for s in trigger_stats if s["key"] == "sos"), None)
    if pure_sos and isinstance(pure_sos["avg"], float) and pure_sos["avg"] < 0:
        lines.append(
            f"- 纯 SOS 信号本轮均收 {_fmt_signed(pure_sos['avg'], 2, '%')}，建议后续测试 `SOS+EVR/Spring/LPS` 或次日跟随确认，避免宽口径突破噪音。"
        )
    lines.append(
        "- 后续每次手动 Backtest Grid 完成后，workflow 会生成本报告并上传为 artifact；仓库内文档只在人工确认后提交更新。"
    )
    return lines


def _build_ranked_table(ranked: list[GridCell], best: GridCell) -> list[str]:
    lines = [
        "",
        "## 参数梯队（按现金收益）",
        "",
        "| 排名 | 参数组合 | 夏普 | 胜率 | 均收 | 现金回撤 | 最终现金 | 现金收益 | 样本 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, cell in enumerate(ranked, 1):
        marker = " 🏆" if cell == best else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    _fmt_param(cell),
                    f"{_fmt_num(cell.sharpe, 3)}{marker}",
                    _fmt_num(cell.win_rate, 1, "%"),
                    _fmt_signed(cell.avg_ret, 2, "%"),
                    _fmt_num(_cash_drawdown(cell), 1, "%"),
                    _fmt_num(cell.cash_final, 2),
                    _fmt_signed(cell.cash_total_return, 2, "%"),
                    str(cell.trades or 0),
                ]
            )
            + " |"
        )
    return lines


def _build_trade_structure_lines(diagnostics: dict[str, object]) -> list[str]:
    return [
        "",
        "## 最优组合交易结构",
        "",
        f"- 交易笔数: {diagnostics['count']}；盈利 {diagnostics['wins']}；亏损 {diagnostics['losses']}",
        f"- 单笔胜率: {_fmt_num(diagnostics['win_rate'], 2, '%')}",
        f"- 盈利单均值: {_fmt_signed(diagnostics['avg_win'], 2, '%')}",
        f"- 亏损单均值: {_fmt_signed(diagnostics['avg_loss'], 2, '%')}",
        f"- 盈亏比: {_fmt_num(diagnostics['payoff'], 2)}",
        f"- 单笔中位数: {_fmt_signed(diagnostics['median_all'], 2, '%')}",
    ]


def _build_regime_stats_table(regime_stats: list[dict[str, object]]) -> list[str]:
    lines = [
        "",
        "## 市场周期分层",
        "",
        "| 周期 | 含义 | 笔数 | 信号期 | 胜率 | 均收 | 中位数 |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for stat in regime_stats:
        key = str(stat["key"])
        date_range = f"{stat['first_date']} ~ {stat['last_date']}" if stat["first_date"] else "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    key,
                    REGIME_LABELS.get(key, "-"),
                    str(stat["count"]),
                    date_range,
                    _fmt_num(stat["win_rate"], 1, "%"),
                    _fmt_signed(stat["avg"], 2, "%"),
                    _fmt_signed(stat["median"], 2, "%"),
                ]
            )
            + " |"
        )
    return lines


def _build_trigger_stats_table(trigger_stats: list[dict[str, object]]) -> list[str]:
    lines = ["", "## 信号类型分层", "", "| 信号 | 笔数 | 胜率 | 均收 | 中位数 |", "|---|---:|---:|---:|---:|"]
    for stat in trigger_stats:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(stat["key"]),
                    str(stat["count"]),
                    _fmt_num(stat["win_rate"], 1, "%"),
                    _fmt_signed(stat["avg"], 2, "%"),
                    _fmt_signed(stat["median"], 2, "%"),
                ]
            )
            + " |"
        )
    return lines


def _build_methodology_notes() -> list[str]:
    return [
        "",
        "## 口径说明",
        "",
        "- 胜率是单笔交易 `ret_pct > 0` 的比例，不是组合每日正收益比例。",
        "- 入场口径以各参数单元 summary 为准；当前 workflow 默认 T+1 开盘价，`tail_1455` 模式缺分钟线时按 `BACKTEST_ENTRY_PRICE_FALLBACK` 处理。",
        "- `可完整验证信号期` 会早于回测结束日，因为持有窗口需要足够后续交易日完成离场验证。",
        "- 本结果仍可能包含当前股票池幸存者偏差，以及当前截面市值/行业映射带来的前视偏差；用于参数方向和市场周期适配判断，不等同于实盘承诺。",
        "",
    ]


def build_report(cells: list[GridCell], run_url: str = "", generated_at: str = "") -> str:
    if not cells:
        raise ValueError("未找到可解析的 backtest summary artifacts")

    ranked = sorted(cells, key=_cash_sort_key, reverse=True)
    robust_ranked = _rank_robust_params(cells)
    robust_best = robust_ranked[0] if robust_ranked else None
    best = robust_best.best_cell if robust_best else ranked[0]
    best_sharpe_cell = max(cells, key=_cell_sort_key)
    best_rows = read_trades(best.trades_path)
    diagnostics = _build_trade_diagnostics(best_rows)
    regime_stats = _group_stats(best_rows, lambda r: r.get("regime", ""))
    trigger_stats = _group_stats(best_rows, lambda r: r.get("trigger", ""))
    current_cycle, cycle_detail = _latest_cycle(best_rows)

    generated = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pos_sharpe = sum(1 for c in cells if (c.sharpe or 0) > 0)
    neg_sharpe = len(cells) - pos_sharpe
    period_best_table = _build_period_best_table(cells)
    style_best_table = _build_style_best_table(cells)
    robust_param_table = _build_robust_param_table(robust_ranked)

    lines = _build_execution_context_lines(
        cells=cells,
        best=best,
        diagnostics=diagnostics,
        current_cycle=current_cycle,
        cycle_detail=cycle_detail,
        generated=generated,
        pos_sharpe=pos_sharpe,
        neg_sharpe=neg_sharpe,
        run_url=run_url,
    )
    lines.extend(_build_conclusion_lines(cells=cells, best=best, robust_best=robust_best, diagnostics=diagnostics))

    lines.extend(period_best_table)
    lines.extend(style_best_table)
    lines.extend(robust_param_table)
    lines.extend(_build_ranked_table(ranked, best))

    lines.extend(["", "## 最优夏普矩阵", "", *_build_matrix(cells, best_sharpe_cell)])
    lines.extend(_build_trade_structure_lines(diagnostics))
    lines.extend(_build_regime_stats_table(regime_stats))
    lines.extend(_build_trigger_stats_table(trigger_stats))
    lines.extend(_build_followup_lines(regime_stats, trigger_stats))
    lines.extend(_build_methodology_notes())
    return "\n".join(lines)
