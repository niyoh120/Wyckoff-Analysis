"""Tail Buy intraday job orchestration."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import time

from core.tail_buy.strategy import TailBuyCandidate, merge_rule_and_llm
from integrations.tickflow_client import TickFlowClient
from integrations.tickflow_notice import TICKFLOW_UPGRADE_URL
from utils.trading_clock import is_a_share_trading_day
from workflows.tail_buy_candidates import (
    has_signal_pending_on_date,
    load_tail_candidates,
    resolve_tail_buy_trade_dates,
)
from workflows.tail_buy_delivery import (
    notify_tail_buy_non_trading_day,
    persist_tail_buy_results,
    resolve_market_reminder,
    send_tail_buy_report,
    send_tail_buy_skip_notice,
)
from workflows.tail_buy_holdings import analyze_holdings_actions, build_holdings_markdown
from workflows.tail_buy_llm_overlay import apply_tail_buy_depth_filter, run_llm_overlay
from workflows.tail_buy_market_repair import (
    append_intraday_market_reminder,
    apply_intraday_market_mode,
    resolve_intraday_market_mode,
)
from workflows.tail_buy_rule_scan import log_fetch_error_summary, run_rule_scan, run_rule_scan_batch
from workflows.tail_buy_runtime import (
    TailBuyCandidateRun,
    TailBuyRuntimeConfig,
    build_tail_buy_runtime_config,
    default_tail_buy_portfolio_id,
    plan_intraday_scan_budget,
)
from workflows.tail_buy_utils import current_time, log_line, now_text


@dataclass(frozen=True)
class TailBuyJobRequest:
    max_llm_symbols: int
    deadline_minute: int
    portfolio_id: str
    logs: str | None = None
    user_id: str = ""
    mode: str = "auto"


@dataclass(frozen=True)
class TailBuyRunPlan:
    mode: str
    target_signal_date: str
    today_trade_date: str
    strict_signal_date: bool
    include_holding_candidates: bool
    persist_results: bool
    skip_reason: str = ""


def default_tail_buy_job_portfolio_id() -> str:
    return default_tail_buy_portfolio_id()


def run_tail_buy_intraday_job(request: TailBuyJobRequest) -> int:
    config = build_tail_buy_runtime_config(request, current_time())
    if not is_a_share_trading_day():
        return notify_tail_buy_non_trading_day(config)
    log_tail_buy_runtime_config(config)
    validation_status = validate_tail_buy_runtime_config(config)
    if validation_status is not None:
        return validation_status
    return _run_tail_buy_trading_day(request, config)


def log_tail_buy_runtime_config(config: TailBuyRuntimeConfig) -> None:
    log_line("开始 Tail Buy 任务", config.logs_path)
    log_line(_runtime_config_line(config), config.logs_path)
    log_line(
        "LLM routes: " + " -> ".join([x["name"] for x in config.llm_routes])
        if config.llm_routes
        else "LLM routes: disabled",
        config.logs_path,
    )


def validate_tail_buy_runtime_config(config: TailBuyRuntimeConfig) -> int | None:
    if not config.tickflow_api_key:
        log_line(f"缺少 TICKFLOW_API_KEY，Tail Buy 需要分钟级数据，请购买：{TICKFLOW_UPGRADE_URL}", config.logs_path)
        return 1
    if not config.feishu_webhook:
        log_line("缺少 FEISHU_WEBHOOK_URL，Tail Buy 需要至少配置飞书推送；Telegram 为可选通道。", config.logs_path)
        return 1
    if not config.tg_bot_token or not config.tg_chat_id:
        log_line("Telegram 未完整配置，将仅使用飞书推送。", config.logs_path)
    return None


def resolve_tail_buy_run_plan(config: TailBuyRuntimeConfig) -> TailBuyRunPlan:
    prev_trade_date, today_trade_date = resolve_tail_buy_trade_dates(config.logs_path)
    requested_mode = str(config.mode or "auto").strip().lower()
    if requested_mode == "intraday":
        return _intraday_run_plan(prev_trade_date, today_trade_date)
    if requested_mode == "post_close_review":
        return _post_close_run_plan(today_trade_date, config, require_today_result=True)
    if _is_post_close_time(config.started_at):
        return _post_close_run_plan(today_trade_date, config, require_today_result=True)
    return _intraday_run_plan(prev_trade_date, today_trade_date)


def load_tail_buy_inputs(
    config: TailBuyRuntimeConfig,
    plan: TailBuyRunPlan,
) -> tuple[list[TailBuyCandidate], str] | None:
    try:
        pending_candidates, candidate_source_desc = load_tail_candidates(
            plan.target_signal_date,
            config.portfolio_id,
            config.logs_path,
            lookback_days=0 if plan.strict_signal_date else 15,
            strict_signal_date=plan.strict_signal_date,
            include_holdings=plan.include_holding_candidates,
        )
    except Exception as e:
        log_line(f"读取候选池失败: {e}", config.logs_path)
        return None
    return pending_candidates, candidate_source_desc


def build_tail_buy_holdings_section(
    *,
    tickflow_client: TickFlowClient,
    pending_candidates: list[TailBuyCandidate],
    config: TailBuyRuntimeConfig,
) -> str:
    signal_map = {x.code: x for x in pending_candidates}
    holdings, holdings_limit_hit, portfolio_meta = analyze_holdings_actions(
        tickflow_client=tickflow_client,
        portfolio_id=config.portfolio_id,
        signal_map=signal_map,
        style=config.style,
        intraday_batch_size=config.intraday_batch_size,
        hard_stop_pct=config.holding_hard_stop_pct,
        strategy_config=config.strategy_config,
        deadline_at=config.deadline_at,
        logs_path=config.logs_path,
    )
    return build_holdings_markdown(
        holdings=holdings,
        portfolio_meta=portfolio_meta,
        tickflow_limit_hit=holdings_limit_hit,
    )


def run_tail_buy_rule_scan(
    pending_candidates: list[TailBuyCandidate],
    *,
    tickflow_client: TickFlowClient,
    config: TailBuyRuntimeConfig,
) -> list[TailBuyCandidate]:
    scored = run_tail_buy_batch_rule_scan(pending_candidates, tickflow_client=tickflow_client, config=config)
    return scored or run_tail_buy_single_rule_scan(pending_candidates, tickflow_client=tickflow_client, config=config)


def run_tail_buy_batch_rule_scan(
    pending_candidates: list[TailBuyCandidate],
    *,
    tickflow_client: TickFlowClient,
    config: TailBuyRuntimeConfig,
) -> list[TailBuyCandidate]:
    if not config.use_batch_intraday:
        return []
    log_line(
        f"规则扫描模式: batch（batch_size={config.intraday_batch_size}, candidates={len(pending_candidates)}）",
        config.logs_path,
    )
    scored = run_rule_scan_batch(
        pending_candidates,
        tickflow_client=tickflow_client,
        style=config.style,
        strategy_config=config.strategy_config,
        batch_size=config.intraday_batch_size,
        deadline_at=config.deadline_at,
        logs_path=config.logs_path,
    )
    if scored and _hard_batch_failure_count(scored) >= len(scored):
        log_line("批量接口全部失败，降级到单标的限流模式。", config.logs_path)
        return []
    return scored


def run_tail_buy_single_rule_scan(
    pending_candidates: list[TailBuyCandidate],
    *,
    tickflow_client: TickFlowClient,
    config: TailBuyRuntimeConfig,
) -> list[TailBuyCandidate]:
    to_scan_count, planned_over_limit = plan_intraday_scan_budget(
        len(pending_candidates),
        limit_per_min=config.intraday_limit_per_min,
        max_over_limit_symbols=config.max_over_limit_symbols,
        force_over_limit=config.force_over_limit,
    )
    to_scan, deferred = pending_candidates[:to_scan_count], pending_candidates[to_scan_count:]
    _log_scan_budget(pending_candidates, to_scan, deferred, planned_over_limit, config)
    _mark_deferred_candidates(deferred, len(to_scan), config)
    scored = run_rule_scan(
        to_scan,
        tickflow_client=tickflow_client,
        style=config.style,
        fetch_concurrency=config.fetch_concurrency,
        strategy_config=config.strategy_config,
        deadline_at=config.deadline_at,
        logs_path=config.logs_path,
    )
    scored.extend(deferred)
    scored.sort(key=lambda x: (-x.rule_score, x.code))
    return scored


def run_tail_buy_candidate_flow(
    pending_candidates: list[TailBuyCandidate],
    *,
    tickflow_client: TickFlowClient,
    config: TailBuyRuntimeConfig,
) -> TailBuyCandidateRun:
    if not pending_candidates:
        log_line("候选池为空：本轮仅输出持仓动作建议。", config.logs_path)
        return TailBuyCandidateRun([], 0, 0, {}, "")
    data_fetched_at = now_text()
    scored = run_tail_buy_rule_scan(pending_candidates, tickflow_client=tickflow_client, config=config)
    depth_map = apply_tail_buy_depth_filter(scored, tickflow_client=tickflow_client, config=config)
    llm_map, llm_total, llm_success, llm_route_stats = run_llm_overlay(
        scored,
        llm_routes=config.llm_routes,
        style=config.style,
        max_llm_symbols=config.max_llm_symbols,
        min_rule_score=config.llm_min_rule_score,
        allowed_rule_decisions=config.llm_allowed_rule_decisions,
        llm_concurrency=config.llm_concurrency,
        deadline_at=config.deadline_at,
        depth_map=depth_map,
        logs_path=config.logs_path,
    )
    return TailBuyCandidateRun(
        merged=merge_rule_and_llm(scored, llm_map, config=config.strategy_config),
        llm_total=llm_total,
        llm_success=llm_success,
        llm_route_stats=llm_route_stats,
        data_fetched_at=data_fetched_at,
    )


def _run_tail_buy_trading_day(request: TailBuyJobRequest, config: TailBuyRuntimeConfig) -> int:
    plan = resolve_tail_buy_run_plan(config)
    log_line(_run_plan_line(plan), config.logs_path)
    if plan.skip_reason:
        return send_tail_buy_skip_notice(
            config,
            title="盘后尾盘复核跳过",
            message=plan.skip_reason,
        )
    inputs = load_tail_buy_inputs(config, plan)
    if inputs is None:
        return 1
    pending_candidates, candidate_source_desc = inputs
    tickflow_client = TickFlowClient(api_key=config.tickflow_api_key, max_retries=config.tickflow_task_retries)
    market_reminder = resolve_market_reminder(plan.today_trade_date)
    market_mode, market_mode_reason = resolve_intraday_market_mode(
        tickflow_client,
        market_reminder=market_reminder,
        logs_path=config.logs_path,
    )
    apply_intraday_market_mode(pending_candidates, mode=market_mode, logs_path=config.logs_path)
    market_reminder = append_intraday_market_reminder(market_reminder, market_mode, market_mode_reason)
    holdings_section = build_tail_buy_holdings_section(
        tickflow_client=tickflow_client,
        pending_candidates=pending_candidates,
        config=config,
    )
    run_result = run_tail_buy_candidate_flow(pending_candidates, tickflow_client=tickflow_client, config=config)
    elapsed = (current_time() - config.started_at).total_seconds()
    feishu_ok, tg_ok = _finalize_tail_buy_run(
        request=request,
        config=config,
        plan=plan,
        run_result=run_result,
        market_reminder=market_reminder,
        candidate_source_desc=candidate_source_desc,
        holdings_section=holdings_section,
        elapsed=elapsed,
    )
    return 0 if _tail_buy_delivery_succeeded(config, feishu_ok, tg_ok) else 1


def _finalize_tail_buy_run(
    *,
    request: TailBuyJobRequest,
    config: TailBuyRuntimeConfig,
    plan: TailBuyRunPlan,
    run_result: TailBuyCandidateRun,
    market_reminder: str,
    candidate_source_desc: str,
    holdings_section: str,
    elapsed: float,
) -> tuple[bool, bool]:
    _log_final_decision_distribution(run_result, config.logs_path)
    log_fetch_error_summary(run_result.merged, stage="最终输出", logs_path=config.logs_path)
    if plan.persist_results:
        persist_tail_buy_results(run_result.merged, config.started_at, request.user_id, config.logs_path)
    else:
        log_line("盘后复核模式：不写 tail_buy_history / Supabase BUY，只输出明日计划。", config.logs_path)
    feishu_ok, tg_ok = send_tail_buy_report(
        config=config,
        target_signal_date=plan.target_signal_date,
        market_reminder=market_reminder,
        candidate_source_desc=candidate_source_desc,
        holdings_section=holdings_section,
        run_result=run_result,
        elapsed=elapsed,
        report_mode=plan.mode,
    )
    log_line(_final_summary_line(run_result, feishu_ok, tg_ok, elapsed), config.logs_path)
    return feishu_ok, tg_ok


def _runtime_config_line(config: TailBuyRuntimeConfig) -> str:
    return (
        f"config: provider={config.provider}, primary_route={config.primary_route}, style={config.style}, "
        f"fetch_concurrency={config.fetch_concurrency}, llm_concurrency={config.llm_concurrency}, "
        f"max_llm_symbols={config.max_llm_symbols}, llm_min_rule_score={config.llm_min_rule_score}, "
        f"llm_allowed_rule_decisions={','.join(config.llm_allowed_rule_decisions)}, deadline={config.deadline_min}m, "
        f"portfolio_id={config.portfolio_id}, holding_hard_stop_pct={config.holding_hard_stop_pct}, "
        f"intraday_limit={config.intraday_limit_per_min}/min, max_over_limit={config.max_over_limit_symbols}, "
        f"force_over_limit={config.force_over_limit}, tickflow_retries={config.tickflow_task_retries}, "
        f"use_batch_intraday={config.use_batch_intraday}, intraday_batch_size={config.intraday_batch_size}, "
        f"confirmed_only_buy={config.strategy_config.confirmed_only_buy}, mode={config.mode}"
    )


def _intraday_run_plan(prev_trade_date: str, today_trade_date: str) -> TailBuyRunPlan:
    return TailBuyRunPlan(
        mode="intraday",
        target_signal_date=prev_trade_date,
        today_trade_date=today_trade_date,
        strict_signal_date=False,
        include_holding_candidates=True,
        persist_results=True,
    )


def _post_close_run_plan(
    today_trade_date: str,
    config: TailBuyRuntimeConfig,
    *,
    require_today_result: bool,
) -> TailBuyRunPlan:
    if require_today_result and not has_signal_pending_on_date(today_trade_date, config.logs_path):
        return TailBuyRunPlan(
            mode="post_close_review",
            target_signal_date=today_trade_date,
            today_trade_date=today_trade_date,
            strict_signal_date=True,
            include_holding_candidates=False,
            persist_results=False,
            skip_reason=f"今天 {today_trade_date} 的漏斗二次确认结果尚未写入 signal_pending，跳过盘后复核，避免复用旧候选。",
        )
    return TailBuyRunPlan(
        mode="post_close_review",
        target_signal_date=today_trade_date,
        today_trade_date=today_trade_date,
        strict_signal_date=True,
        include_holding_candidates=False,
        persist_results=False,
    )


def _is_post_close_time(dt) -> bool:
    return dt.timetz().replace(tzinfo=None) >= time(15, 5)


def _run_plan_line(plan: TailBuyRunPlan) -> str:
    return (
        f"run_plan: mode={plan.mode}, target_signal_date={plan.target_signal_date}, "
        f"today_trade_date={plan.today_trade_date}, strict={plan.strict_signal_date}, "
        f"include_holdings={plan.include_holding_candidates}, persist={plan.persist_results}"
    )


def _tail_buy_delivery_succeeded(config: TailBuyRuntimeConfig, feishu_ok: bool, tg_ok: bool) -> bool:
    tg_required = bool(config.tg_bot_token and config.tg_chat_id)
    return bool(feishu_ok and (tg_ok or not tg_required))


def _log_scan_budget(
    pending_candidates: list[TailBuyCandidate],
    to_scan: list[TailBuyCandidate],
    deferred: list[TailBuyCandidate],
    planned_over_limit: int,
    config: TailBuyRuntimeConfig,
) -> None:
    log_line(
        f"分时扫描预算(single): total={len(pending_candidates)}, to_scan={len(to_scan)}, "
        f"deferred={len(deferred)}, limit={config.intraday_limit_per_min}/min, planned_over_limit={planned_over_limit}",
        config.logs_path,
    )


def _mark_deferred_candidates(
    deferred: list[TailBuyCandidate], scanned_count: int, config: TailBuyRuntimeConfig
) -> None:
    if not deferred:
        return
    defer_reason = (
        f"限流保护：本轮仅扫描前 {scanned_count} 只（TickFlow预算 {config.intraday_limit_per_min}/min，"
        f"超限缓冲 <= {config.max_over_limit_symbols} 只）"
    )
    for item in deferred:
        item.fetch_error = defer_reason
        item.rule_reasons = [defer_reason]


def _log_final_decision_distribution(run_result: TailBuyCandidateRun, logs_path: str | None) -> None:
    decision_counter = Counter([str(x.final_decision or "").strip() or "UNKNOWN" for x in run_result.merged])
    log_line(
        "最终决策分布: " + ", ".join([f"{k}={v}" for k, v in sorted(decision_counter.items())]),
        logs_path,
    )


def _hard_batch_failure_count(scored: list[TailBuyCandidate]) -> int:
    return sum(1 for x in scored if "TickFlow批量分时拉取失败" in str(x.fetch_error or ""))


def _final_summary_line(run_result: TailBuyCandidateRun, feishu_ok: bool, tg_ok: bool, elapsed: float) -> str:
    return (
        f"任务结束: candidates={len(run_result.merged)}, llm={run_result.llm_success}/{run_result.llm_total}, "
        f"llm_routes_hit={run_result.llm_route_stats}, feishu_ok={feishu_ok}, tg_ok={tg_ok}, elapsed={elapsed:.1f}s"
    )
