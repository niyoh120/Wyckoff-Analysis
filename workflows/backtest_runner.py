"""Backtest runner workflow orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from core.backtest_run import parse_date
from workflows.backtest import BacktestWorkflowRequest, run_backtest_request
from workflows.backtest_artifacts import (
    backtest_stamp,
    error_suite_row,
    success_suite_row,
    write_backtest_artifacts,
    write_suite_summary,
)
from workflows.backtest_cli import parse_hold_days_list
from workflows.backtest_defaults import FUNNEL_AI_SELECTION_MODE

logger = logging.getLogger(__name__)


def run_backtest_runner(args, progress=None) -> int:
    if progress is None:
        from utils.progress import report_progress

        progress = report_progress
    start_dt = parse_date(args.start)
    end_dt = parse_date(args.end)
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    hold_days_list = _hold_days_list(args)

    suite_rows: list[dict] = []
    success_count = 0
    last_error: Exception | None = None
    for hold_days in hold_days_list:
        try:
            row = run_one_hold_days(args, start_dt, end_dt, out_dir, hold_days, progress)
        except Exception as exc:
            last_error = exc
            logger.error("hold_days=%d 失败: %s", hold_days, exc, exc_info=True)
            suite_rows.append(error_suite_row(hold_days, str(exc)))
            continue
        success_count += 1
        suite_rows.append(row)

    if success_count == 0:
        raise RuntimeError("多周期回测全部失败，请检查日期区间、快照覆盖范围或 TUSHARE_TOKEN。") from last_error

    write_suite_summary(
        out_dir=out_dir,
        start_dt=start_dt,
        end_dt=end_dt,
        suite_rows=suite_rows,
        success_count=success_count,
        candidate_mode=FUNNEL_AI_SELECTION_MODE,
    )
    return 0


def run_one_hold_days(args, start_dt, end_dt, out_dir: Path, hold_days: int, progress) -> dict:
    trades_df, summary = run_backtest_request(
        request_from_args(args, start_dt, end_dt, hold_days),
        progress=progress,
    )
    stamp = backtest_stamp(start_dt, end_dt, hold_days, args.top_n)
    artifact = write_backtest_artifacts(out_dir=out_dir, stamp=stamp, trades_df=trades_df, summary=summary)
    print(artifact.summary_md)
    print("")
    logger.info("summary -> %s", artifact.summary_path)
    logger.info("trades  -> %s", artifact.trades_path)
    return success_suite_row(hold_days, summary)


def request_from_args(args, start_dt, end_dt, hold_days: int) -> BacktestWorkflowRequest:
    return BacktestWorkflowRequest(
        start_dt=start_dt,
        end_dt=end_dt,
        hold_days=hold_days,
        top_n=args.top_n,
        board=args.board,
        sample_size=args.sample_size,
        trading_days=args.trading_days,
        max_workers=args.workers,
        snapshot_dir=Path(args.snapshot_dir).resolve() if str(args.snapshot_dir).strip() else None,
        benchmark=args.benchmark,
        exit_mode=args.exit_mode,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
        trailing_stop_pct=args.trailing_stop,
        trailing_activate_pct=args.trailing_activate,
        sltp_priority=args.sltp_priority,
        use_current_meta=args.use_current_meta,
        buy_friction_pct=args.buy_friction_pct,
        sell_friction_pct=args.sell_friction_pct,
        regime_filter=args.regime_filter,
        pending_mode=args.pending_mode,
        pending_merge_order=args.pending_merge_order,
        atr_period=args.atr_period,
        atr_multiplier=args.atr_multiplier,
        atr_hard_stop_pct=args.atr_hard_stop,
        metrics_engine=args.metrics_engine,
        wbt_fee_rate=args.wbt_fee_rate,
        wbt_n_jobs=args.wbt_n_jobs,
        abc_filter=args.abc_filter,
        entry_price_mode=args.entry_price_mode,
        entry_price_time=args.entry_price_time,
        entry_price_fallback=args.entry_price_fallback,
        cash_portfolio=args.cash_portfolio,
        initial_cash=args.initial_cash,
        max_positions=args.max_positions,
        commission_rate=args.commission_rate,
        small_trade_threshold=args.small_trade_threshold,
        small_trade_fee=args.small_trade_fee,
        lot_size=args.lot_size,
        portfolio_styles=args.portfolio_styles,
    )


def _hold_days_list(args) -> list[int]:
    raw = str(args.hold_days_list or "").strip()
    return parse_hold_days_list(raw) if raw else [int(args.hold_days)]
