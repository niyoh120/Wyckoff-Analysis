"""Rule-scan workflow for tail-buy intraday candidates."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime

from core.tail_buy.strategy import TailBuyCandidate, TailBuyStrategyConfig, evaluate_rule_decision
from integrations.tickflow_client import TickFlowClient, normalize_cn_symbol
from workflows.tail_buy_utils import chunked, log_line, remaining_seconds, with_tickflow_upgrade_hint


@dataclass
class _BatchScanStats:
    skipped_due_deadline: int = 0
    batch_fail_symbols: int = 0
    batch_rate_limited_symbols: int = 0


def log_fetch_error_summary(
    items: list[TailBuyCandidate],
    *,
    stage: str,
    logs_path: str | None = None,
) -> None:
    reasons = [str(item.fetch_error or "").strip() for item in items if str(item.fetch_error or "").strip()]
    if not reasons:
        log_line(f"{stage}失败汇总: 无", logs_path)
        return
    counter = Counter(reasons)
    summary = " | ".join(f"{reason[:80]} x{cnt}" for reason, cnt in counter.most_common(5))
    log_line(f"{stage}失败汇总: total={len(reasons)}, unique={len(counter)}, top={summary}", logs_path)


def run_rule_scan(
    candidates: list[TailBuyCandidate],
    *,
    tickflow_client: TickFlowClient,
    style: str,
    strategy_config: TailBuyStrategyConfig,
    fetch_concurrency: int,
    deadline_at: datetime,
    logs_path: str | None = None,
) -> list[TailBuyCandidate]:
    if not candidates:
        return []
    scanned: list[TailBuyCandidate] = []
    futures: dict = {}
    skipped = 0
    max_workers = max(int(fetch_concurrency), 1)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        skipped = _submit_symbol_scans(
            executor, futures, scanned, candidates, tickflow_client, style, strategy_config, deadline_at
        )
        scanned.extend(_collect_symbol_scans(futures, deadline_at, logs_path))
    return _finish_rule_scan(scanned, skipped, max_workers, "规则扫描(single)", logs_path)


def run_rule_scan_batch(
    candidates: list[TailBuyCandidate],
    *,
    tickflow_client: TickFlowClient,
    style: str,
    strategy_config: TailBuyStrategyConfig,
    batch_size: int,
    deadline_at: datetime,
    logs_path: str | None = None,
) -> list[TailBuyCandidate]:
    if not candidates:
        return []
    chunks = chunked(candidates, max(min(int(batch_size), 200), 1))
    scanned: list[TailBuyCandidate] = []
    stats = _BatchScanStats()
    for idx, batch in enumerate(chunks, start=1):
        scanned.extend(
            _scan_batch_chunk(
                idx, chunks, batch, tickflow_client, style, strategy_config, deadline_at, stats, logs_path
            )
        )
    return _finish_batch_scan(scanned, stats, batch_size, logs_path)


def _submit_symbol_scans(
    executor: ThreadPoolExecutor,
    futures: dict,
    scanned: list[TailBuyCandidate],
    candidates: list[TailBuyCandidate],
    tickflow_client: TickFlowClient,
    style: str,
    strategy_config: TailBuyStrategyConfig,
    deadline_at: datetime,
) -> int:
    skipped = 0
    for item in candidates:
        if remaining_seconds(deadline_at) <= 5:
            skipped += 1
            scanned.append(_mark_scan_failure(item, "超出任务时限，未执行分时扫描"))
            continue
        future = executor.submit(_scan_one_symbol, tickflow_client, item, style=style, strategy_config=strategy_config)
        futures[future] = item.code
    return skipped


def _collect_symbol_scans(
    futures: dict,
    deadline_at: datetime,
    logs_path: str | None,
) -> list[TailBuyCandidate]:
    scanned: list[TailBuyCandidate] = []
    timeout_seconds = max(1, int(remaining_seconds(deadline_at)))
    try:
        for future in as_completed(futures, timeout=timeout_seconds):
            scanned.append(_symbol_scan_result(future, futures))
    except FutureTimeout:
        log_line("规则扫描触发 deadline 保护：停止等待剩余任务。", logs_path)
        scanned.extend(_cancel_pending_symbol_scans(futures))
    return scanned


def _scan_one_symbol(
    client: TickFlowClient,
    candidate: TailBuyCandidate,
    *,
    style: str,
    strategy_config: TailBuyStrategyConfig,
) -> TailBuyCandidate:
    symbol = normalize_cn_symbol(candidate.code)
    try:
        df_1m = client.get_intraday(symbol, period="1m", count=5000)
    except Exception as exc:
        return _mark_scan_failure(candidate, with_tickflow_upgrade_hint(f"TickFlow分钟数据拉取失败: {exc}"))
    if df_1m is None or df_1m.empty:
        return _mark_scan_failure(candidate, "TickFlow返回空分时")
    try:
        return evaluate_rule_decision(candidate, df_1m, style=style, config=strategy_config)
    except Exception as exc:
        return _mark_scan_failure(candidate, f"规则评分失败: {exc}")


def _scan_batch_chunk(
    idx: int,
    chunks: list[list[TailBuyCandidate]],
    batch: list[TailBuyCandidate],
    tickflow_client: TickFlowClient,
    style: str,
    strategy_config: TailBuyStrategyConfig,
    deadline_at: datetime,
    stats: _BatchScanStats,
    logs_path: str | None,
) -> list[TailBuyCandidate]:
    log_line(_batch_progress_text(idx, chunks, batch, deadline_at), logs_path)
    if remaining_seconds(deadline_at) <= 5:
        stats.skipped_due_deadline += len(batch)
        return [_mark_scan_failure(item, "超出任务时限，未执行分时扫描") for item in batch]
    try:
        data_map = tickflow_client.get_intraday_batch(_batch_symbols(batch), period="1m", count=5000)
    except Exception as exc:
        return _mark_batch_fetch_failure(idx, chunks, batch, exc, stats, logs_path)
    log_line(f"规则扫描(batch): chunk={idx}/{len(chunks)} data_hit={len(data_map)}/{len(batch)}", logs_path)
    return _evaluate_batch_rows(batch, data_map, style, strategy_config)


def _evaluate_batch_rows(
    batch: list[TailBuyCandidate],
    data_map: dict,
    style: str,
    strategy_config: TailBuyStrategyConfig,
) -> list[TailBuyCandidate]:
    scanned: list[TailBuyCandidate] = []
    for item in batch:
        df_1m = data_map.get(normalize_cn_symbol(item.code))
        if df_1m is None or df_1m.empty:
            scanned.append(_mark_scan_failure(item, "TickFlow返回空分时"))
            continue
        try:
            scanned.append(evaluate_rule_decision(item, df_1m, style=style, config=strategy_config))
        except Exception as exc:
            scanned.append(_mark_scan_failure(item, f"规则评分失败: {exc}"))
    return scanned


def _mark_batch_fetch_failure(
    idx: int,
    chunks: list[list[TailBuyCandidate]],
    batch: list[TailBuyCandidate],
    exc: Exception,
    stats: _BatchScanStats,
    logs_path: str | None,
) -> list[TailBuyCandidate]:
    reason = with_tickflow_upgrade_hint(f"TickFlow批量分时拉取失败: {exc}")
    stats.batch_fail_symbols += len(batch)
    if "429" in str(exc) or "RATE_LIMITED" in str(exc):
        stats.batch_rate_limited_symbols += len(batch)
    log_line(f"规则扫描(batch): chunk={idx}/{len(chunks)} failed, affected={len(batch)}, err={exc}", logs_path)
    return [_mark_scan_failure(item, reason) for item in batch]


def _finish_rule_scan(
    scanned: list[TailBuyCandidate],
    skipped_due_deadline: int,
    max_workers: int,
    stage: str,
    logs_path: str | None,
) -> list[TailBuyCandidate]:
    scanned.sort(key=lambda x: (-x.rule_score, x.code))
    if skipped_due_deadline:
        log_line(f"规则扫描: 因 deadline 提前跳过 {skipped_due_deadline} 只", logs_path)
    ok_cnt = sum(1 for item in scanned if not item.fetch_error)
    log_line(
        f"规则扫描完成: total={len(scanned)}, ok={ok_cnt}, fail={len(scanned) - ok_cnt}, workers={max_workers}",
        logs_path,
    )
    log_fetch_error_summary(scanned, stage=stage, logs_path=logs_path)
    return scanned


def _finish_batch_scan(
    scanned: list[TailBuyCandidate],
    stats: _BatchScanStats,
    batch_size: int,
    logs_path: str | None,
) -> list[TailBuyCandidate]:
    scanned.sort(key=lambda x: (-x.rule_score, x.code))
    if stats.skipped_due_deadline:
        log_line(f"规则扫描(batch): 因 deadline 提前跳过 {stats.skipped_due_deadline} 只", logs_path)
    ok_cnt = sum(1 for item in scanned if not item.fetch_error)
    log_line(_batch_finish_text(scanned, ok_cnt, batch_size, stats), logs_path)
    log_fetch_error_summary(scanned, stage="规则扫描(batch)", logs_path=logs_path)
    return scanned


def _symbol_scan_result(future, futures: dict) -> TailBuyCandidate:
    try:
        return future.result()
    except Exception as exc:
        return _failed_scan_candidate(str(futures.get(future, "")), f"并发执行异常: {exc}")


def _cancel_pending_symbol_scans(futures: dict) -> list[TailBuyCandidate]:
    cancelled: list[TailBuyCandidate] = []
    for future, code in futures.items():
        if future.done():
            continue
        future.cancel()
        cancelled.append(_failed_scan_candidate(str(code), "超出任务时限，任务已取消"))
    return cancelled


def _mark_scan_failure(candidate: TailBuyCandidate, reason: str) -> TailBuyCandidate:
    candidate.fetch_error = reason
    candidate.rule_reasons = [reason]
    return candidate


def _failed_scan_candidate(code: str, reason: str) -> TailBuyCandidate:
    return TailBuyCandidate(
        code=code,
        name=code,
        signal_date="",
        status="pending",
        signal_type="unknown",
        signal_score=0.0,
        fetch_error=reason,
        rule_reasons=[reason],
    )


def _batch_symbols(batch: list[TailBuyCandidate]) -> list[str]:
    return [normalize_cn_symbol(item.code) for item in batch]


def _batch_progress_text(
    idx: int,
    chunks: list[list[TailBuyCandidate]],
    batch: list[TailBuyCandidate],
    deadline_at: datetime,
) -> str:
    return (
        f"规则扫描(batch): chunk={idx}/{len(chunks)}, size={len(batch)}, "
        f"time_left={remaining_seconds(deadline_at):.1f}s"
    )


def _batch_finish_text(
    scanned: list[TailBuyCandidate],
    ok_cnt: int,
    batch_size: int,
    stats: _BatchScanStats,
) -> str:
    return (
        f"规则扫描(batch)完成: total={len(scanned)}, ok={ok_cnt}, fail={len(scanned) - ok_cnt}, "
        f"batch_size={max(min(int(batch_size), 200), 1)}, batch_fail_symbols={stats.batch_fail_symbols}, "
        f"batch_rate_limited_symbols={stats.batch_rate_limited_symbols}"
    )
