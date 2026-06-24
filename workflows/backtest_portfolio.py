"""Portfolio backtest workflow and report rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.backtest_metrics import fmt_metric
from core.backtest_portfolio import build_portfolio_nav, calc_portfolio_metrics


@dataclass(frozen=True)
class PortfolioBacktestRequest:
    trades_path: Path
    output_dir: Path
    initial_capital: float = 1_000_000.0
    max_concurrent: int = 5
    weight_mode: str = "equal"


@dataclass(frozen=True)
class PortfolioBacktestResult:
    trades_count: int
    trading_days: int
    metrics: dict
    nav_path: Path
    summary_path: Path
    summary_markdown: str


def run_portfolio_backtest(request: PortfolioBacktestRequest) -> PortfolioBacktestResult:
    trades_path = request.trades_path.resolve()
    if not trades_path.exists():
        raise FileNotFoundError(f"trades 文件不存在: {trades_path}")

    trades_df = pd.read_csv(trades_path, dtype={"code": str})
    nav_df = build_portfolio_nav(
        trades_df,
        initial_capital=request.initial_capital,
        max_concurrent=request.max_concurrent,
        weight_mode=request.weight_mode,
    )
    metrics = calc_portfolio_metrics(nav_df, initial_capital=request.initial_capital)
    nav_path, summary_path = _output_paths(request.output_dir)
    summary_markdown = build_portfolio_markdown(metrics, nav_df)
    _write_outputs(nav_df, summary_markdown, nav_path, summary_path)
    return PortfolioBacktestResult(
        trades_count=len(trades_df),
        trading_days=len(nav_df),
        metrics=metrics,
        nav_path=nav_path,
        summary_path=summary_path,
        summary_markdown=summary_markdown,
    )


def build_portfolio_markdown(metrics: dict, nav_df: pd.DataFrame) -> str:
    lines = [
        "# 组合级回测结果 (Portfolio Backtest)",
        "",
        "## 组合收益",
        f"- 总收益: {fmt_metric(metrics.get('total_return_pct'), 3)}%",
        f"- 年化收益: {fmt_metric(metrics.get('annualized_return_pct'), 3)}%",
        f"- 最终净值: {fmt_metric(metrics.get('final_nav'), 2)}",
        f"- 交易日数: {metrics.get('trading_days', 0)}",
        "",
        "## 风险调整指标",
        f"- 夏普比 (Sharpe): {fmt_metric(metrics.get('sharpe_ratio'), 3)}",
        f"- 卡玛比 (Calmar): {fmt_metric(metrics.get('calmar_ratio'), 3)}",
        f"- 信息比 (IR vs Benchmark): {fmt_metric(metrics.get('information_ratio'), 3)}",
        f"- 最大回撤: {fmt_metric(metrics.get('max_drawdown_pct'), 3)}%",
        f"- VaR95(日): {fmt_metric(metrics.get('var95_daily_pct'), 3)}%",
        f"- CVaR95(日): {fmt_metric(metrics.get('cvar95_daily_pct'), 3)}%",
        "",
        "## 持仓统计",
        f"- 平均持仓数: {fmt_metric(metrics.get('avg_positions'), 1)}",
        f"- 最大同时持仓: {metrics.get('max_positions', 0)}",
        "",
    ]
    lines.extend(_nav_checkpoint_lines(nav_df))
    return "\n".join(lines)


def _nav_checkpoint_lines(nav_df: pd.DataFrame) -> list[str]:
    if nav_df.empty:
        return []
    nav_s = pd.to_numeric(nav_df["nav"], errors="coerce")
    if nav_s.empty:
        return []
    min_idx = nav_s.idxmin()
    return [
        "## 净值关键节点",
        f"- 起点: {nav_df.iloc[0]['date']} | NAV={nav_s.iloc[0]:.2f}",
        f"- 最低: {nav_df.iloc[min_idx]['date']} | NAV={nav_s.iloc[min_idx]:.2f}",
        f"- 终点: {nav_df.iloc[-1]['date']} | NAV={nav_s.iloc[-1]:.2f}",
        "",
    ]


def _output_paths(output_dir: Path) -> tuple[Path, Path]:
    out_dir = output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"portfolio_nav_{stamp}.csv", out_dir / f"portfolio_summary_{stamp}.md"


def _write_outputs(nav_df: pd.DataFrame, markdown: str, nav_path: Path, summary_path: Path) -> None:
    nav_df.to_csv(nav_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(markdown + "\n", encoding="utf-8")
