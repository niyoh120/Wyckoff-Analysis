"""Backtest performance summary and optional portfolio overlays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from core.backtest_execution import (
    TradeRecord,
    build_daily_nav,
    calc_portfolio_metrics,
    cash_mark_price_fn,
    ensure_ohlc_lookup_cache,
)
from core.backtest_metrics import calc_cvar95_pct, calc_max_consecutive_losses, calc_stratified_stats
from core.cash_portfolio import CashPortfolioConfig, simulate_cash_portfolio


@dataclass(frozen=True)
class BacktestPerformanceConfig:
    hold_days: int
    buy_friction_pct: float
    metrics_engine: str
    wbt_fee_rate: float
    wbt_n_jobs: int
    cash_portfolio: bool
    cash_config_by_style: list[CashPortfolioConfig]


def enrich_backtest_summary(
    summary: dict,
    *,
    trades_df: pd.DataFrame,
    records: list[TradeRecord],
    all_df_map: dict[str, pd.DataFrame],
    ohlc_lookup_cache: dict[str, dict[date, tuple[float, float, float, float]]],
    trade_dates: list[date],
    start_dt: date,
    end_dt: date,
    config: BacktestPerformanceConfig,
) -> dict:
    out = dict(summary)
    if trades_df.empty:
        out.update(_empty_trade_metrics(config.metrics_engine))
    else:
        _add_trade_metrics(
            out, trades_df, records, all_df_map, ohlc_lookup_cache, trade_dates, start_dt, end_dt, config
        )
    if config.cash_portfolio:
        _add_cash_portfolio(out, trades_df, all_df_map, ohlc_lookup_cache, config.cash_config_by_style)
    return out


def _empty_trade_metrics(metrics_engine: str) -> dict:
    requested = metrics_engine in {"auto", "both", "wbt"}
    return {
        "win_rate_pct": None,
        "avg_ret_pct": None,
        "median_ret_pct": None,
        "q25_ret_pct": None,
        "q75_ret_pct": None,
        "max_drawdown_pct": None,
        "var95_ret_pct": None,
        "cvar95_ret_pct": None,
        "max_consecutive_losses": 0,
        "sharpe_ratio": None,
        "calmar_ratio": None,
        "portfolio_ann_ret_pct": None,
        "portfolio_total_ret_pct": None,
        "portfolio_trading_days": 0,
        "portfolio_avg_positions": 0.0,
        "stratified": {},
        "wbt_available": False if requested else None,
        "wbt_error": "no trades" if requested else "",
    }


def _add_trade_metrics(
    summary: dict,
    trades_df: pd.DataFrame,
    records: list[TradeRecord],
    all_df_map: dict[str, pd.DataFrame],
    ohlc_lookup_cache: dict[str, dict[date, tuple[float, float, float, float]]],
    trade_dates: list[date],
    start_dt: date,
    end_dt: date,
    config: BacktestPerformanceConfig,
) -> None:
    ret = pd.to_numeric(trades_df["ret_pct"], errors="coerce").dropna()
    var95_ret_pct, cvar95_ret_pct = calc_cvar95_pct(ret)
    ensure_ohlc_lookup_cache(records, all_df_map, ohlc_lookup_cache)
    nav_df = build_daily_nav(records, ohlc_lookup_cache, trade_dates, start_dt, end_dt, config.buy_friction_pct)
    pm = calc_portfolio_metrics(nav_df)
    summary.update(_trade_metric_fields(ret, pm, var95_ret_pct, cvar95_ret_pct, nav_df, trades_df, config.hold_days))
    if config.metrics_engine in {"auto", "both", "wbt"}:
        _add_wbt_metrics(summary, records, all_df_map, ohlc_lookup_cache, trade_dates, start_dt, end_dt, nav_df, config)


def _trade_metric_fields(
    ret: pd.Series,
    portfolio_metrics: dict,
    var95_ret_pct: float | None,
    cvar95_ret_pct: float | None,
    nav_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    hold_days: int,
) -> dict:
    return {
        "win_rate_pct": float((ret > 0).mean() * 100.0),
        "avg_ret_pct": float(ret.mean()),
        "median_ret_pct": float(ret.median()),
        "q25_ret_pct": float(ret.quantile(0.25)),
        "q75_ret_pct": float(ret.quantile(0.75)),
        "max_drawdown_pct": portfolio_metrics.get("portfolio_mdd_pct"),
        "var95_ret_pct": var95_ret_pct,
        "cvar95_ret_pct": cvar95_ret_pct,
        "max_consecutive_losses": calc_max_consecutive_losses(ret),
        "sharpe_ratio": portfolio_metrics.get("portfolio_sharpe"),
        "calmar_ratio": portfolio_metrics.get("portfolio_calmar"),
        "portfolio_ann_ret_pct": portfolio_metrics.get("portfolio_ann_ret_pct"),
        "portfolio_total_ret_pct": portfolio_metrics.get("portfolio_total_ret_pct"),
        "portfolio_trading_days": portfolio_metrics.get("portfolio_trading_days"),
        "portfolio_avg_positions": portfolio_metrics.get("portfolio_avg_positions"),
        "_nav_df": nav_df,
        "stratified": calc_stratified_stats(trades_df, hold_days=hold_days),
    }


def _add_wbt_metrics(
    summary: dict,
    records: list[TradeRecord],
    all_df_map: dict[str, pd.DataFrame],
    ohlc_lookup_cache: dict[str, dict[date, tuple[float, float, float, float]]],
    trade_dates: list[date],
    start_dt: date,
    end_dt: date,
    nav_df: pd.DataFrame,
    config: BacktestPerformanceConfig,
) -> None:
    from core.wbt_adapter import build_position_weight_frame, evaluate_nav_with_wbt, wbt_summary_fields

    wbt_eval = evaluate_nav_with_wbt(nav_df, fee_rate=config.wbt_fee_rate, n_jobs=config.wbt_n_jobs, yearly_days=250)
    if config.metrics_engine == "wbt" and not wbt_eval.available:
        raise RuntimeError(f"metrics_engine=wbt 但 wbt 不可用。请先安装 wbt，当前错误: {wbt_eval.error}")
    summary.update(wbt_summary_fields(wbt_eval))
    if wbt_eval.available:
        summary["wbt_stats"] = wbt_eval.stats or {}
        summary["wbt_long_stats"] = wbt_eval.long_stats or {}
        summary["wbt_short_stats"] = wbt_eval.short_stats or {}
        summary["_wbt_daily_return_df"] = wbt_eval.daily_return
        summary["_wbt_dailys_df"] = wbt_eval.dailys
        summary["_wbt_pairs_df"] = wbt_eval.pairs
    summary["_wbt_weight_df"] = build_position_weight_frame(
        records=records,
        all_df_map=all_df_map,
        ohlc_cache=ohlc_lookup_cache,
        trade_dates=trade_dates,
        start_dt=start_dt,
        end_dt=end_dt,
    )


def _add_cash_portfolio(
    summary: dict,
    trades_df: pd.DataFrame,
    all_df_map: dict[str, pd.DataFrame],
    ohlc_lookup_cache: dict[str, dict[date, tuple[float, float, float, float]]],
    cash_configs: list[CashPortfolioConfig],
) -> None:
    style_summaries: list[dict] = []
    trades_by_style: dict[str, pd.DataFrame] = {}
    nav_by_style: dict[str, pd.DataFrame] = {}
    mark_price_fn = cash_mark_price_fn(all_df_map, ohlc_lookup_cache)
    for cfg in cash_configs:
        cash_trades_df, cash_nav_df, cash_summary = simulate_cash_portfolio(trades_df, cfg, mark_price_fn=mark_price_fn)
        style_summaries.append(cash_summary)
        trades_by_style[cfg.portfolio_style] = cash_trades_df
        nav_by_style[cfg.portfolio_style] = cash_nav_df
    if style_summaries:
        summary.update(style_summaries[0])
    summary["cash_portfolio_style_summaries"] = style_summaries
    summary["_cash_portfolio_trades_by_style"] = trades_by_style
    summary["_cash_portfolio_nav_by_style"] = nav_by_style
