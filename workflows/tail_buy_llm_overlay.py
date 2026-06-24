"""LLM overlay workflow for tail-buy intraday candidates."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime

from core.tail_buy.strategy import (
    TailBuyCandidate,
    build_llm_prompt,
    parse_llm_decision,
    select_llm_overlay_candidates,
)
from integrations.llm_client import call_llm
from integrations.tickflow_client import TickFlowClient
from workflows.tail_buy_runtime import LlmOverlayConfig, LlmOverlayRunResult, TailBuyRuntimeConfig, env_flag
from workflows.tail_buy_utils import log_line, remaining_seconds

DEPTH_WEIBI_SKIP_THRESHOLD = -40.0


def apply_tail_buy_depth_filter(
    scored: list[TailBuyCandidate],
    *,
    tickflow_client: TickFlowClient,
    config: TailBuyRuntimeConfig,
) -> dict[str, dict]:
    if remaining_seconds(config.deadline_at) <= 30:
        return {}
    depth_map = fetch_depth_features(
        tickflow_client,
        sorted([c for c in scored if not c.fetch_error], key=lambda x: (-x.rule_score, x.code)),
        max_symbols=config.max_llm_symbols,
        concurrency=4,
        logs_path=config.logs_path,
    )
    skip_cnt = 0
    for candidate in scored:
        depth_info = depth_map.get(candidate.code)
        if depth_info and depth_info["weibi"] < DEPTH_WEIBI_SKIP_THRESHOLD and candidate.rule_decision != "SKIP":
            candidate.rule_decision = "SKIP"
            candidate.rule_reasons = (candidate.rule_reasons or []) + [f"五档委比={depth_info['weibi']}%，卖压过重"]
            skip_cnt += 1
    if skip_cnt:
        log_line(f"[depth] 委比过滤: {skip_cnt} 只标的被跳过（阈值<{DEPTH_WEIBI_SKIP_THRESHOLD}%）", config.logs_path)
    return depth_map


def run_llm_overlay(
    candidates: list[TailBuyCandidate],
    *,
    llm_routes: list[dict[str, str]],
    style: str,
    max_llm_symbols: int,
    min_rule_score: float,
    allowed_rule_decisions: tuple[str, ...],
    llm_concurrency: int,
    deadline_at: datetime,
    depth_map: dict[str, dict] | None = None,
    logs_path: str | None = None,
) -> tuple[dict[str, dict], int, int, dict[str, int]]:
    if not candidates or max_llm_symbols <= 0:
        return {}, 0, 0, {}
    if not llm_routes:
        log_line("LLM 路由未配置，跳过二判，降级为纯规则结果", logs_path)
        return {}, 0, 0, {}
    if not any(not item.fetch_error for item in candidates):
        return {}, 0, 0, {}
    top_items = select_llm_overlay_items(
        candidates,
        max_llm_symbols=max_llm_symbols,
        min_rule_score=min_rule_score,
        allowed_rule_decisions=allowed_rule_decisions,
        logs_path=logs_path,
    )
    if not top_items:
        log_line("LLM候选过滤后为空：跳过二判，保留纯规则结果。", logs_path)
        return {}, 0, 0, {}
    return collect_llm_overlay(top_items, llm_routes, style, llm_concurrency, deadline_at, depth_map, logs_path)


def fetch_depth_features(
    client: TickFlowClient,
    candidates: list[TailBuyCandidate],
    *,
    max_symbols: int = 20,
    concurrency: int = 4,
    logs_path: str | None = None,
) -> dict[str, dict]:
    top_codes = [c.code for c in candidates if not c.fetch_error][:max_symbols]
    if not top_codes:
        log_line("[depth] 跳过五档: 无可用候选", logs_path)
        return {}
    results: dict[str, dict] = {}
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for code, feat in ex.map(lambda code: _fetch_one_depth(client, code), top_codes):
            if feat:
                results[code] = feat
            else:
                failed.append(code)
    sample = ",".join(failed[:8]) if failed else "-"
    log_line(
        f"[depth] 五档获取完成: ok={len(results)}/{len(top_codes)}, fail={len(failed)}, sample_fail={sample}",
        logs_path,
    )
    return results


def select_llm_overlay_items(
    candidates: list[TailBuyCandidate],
    *,
    max_llm_symbols: int,
    min_rule_score: float,
    allowed_rule_decisions: tuple[str, ...],
    logs_path: str | None,
) -> list[TailBuyCandidate]:
    eligible = [x for x in candidates if not x.fetch_error]
    if not eligible:
        return []
    top_items = select_llm_overlay_candidates(
        eligible,
        max_llm_symbols=max_llm_symbols,
        min_rule_score=min_rule_score,
        allowed_rule_decisions=allowed_rule_decisions,
    )
    log_line(
        "LLM候选过滤: "
        f"eligible={len(eligible)}, selected={len(top_items)}, "
        f"allowed={','.join(allowed_rule_decisions) or 'NONE'}, min_rule_score={min_rule_score:.1f}",
        logs_path,
    )
    return top_items


def collect_llm_overlay(
    top_items: list[TailBuyCandidate],
    llm_routes: list[dict[str, str]],
    style: str,
    llm_concurrency: int,
    deadline_at: datetime,
    depth_map: dict[str, dict] | None,
    logs_path: str | None,
) -> tuple[dict[str, dict], int, int, dict[str, int]]:
    config = LlmOverlayConfig(
        routes=llm_routes,
        style=style,
        deadline_at=deadline_at,
        depth_map=depth_map or {},
        verbose_errors=env_flag("TAIL_BUY_LOG_LLM_PER_SYMBOL_ERRORS", True),
    )
    result = collect_llm_overlay_results(top_items, config=config, llm_concurrency=llm_concurrency, logs_path=logs_path)
    if result.errors:
        top_err = " | ".join([f"{k} x{v}" for k, v in result.errors.most_common(5)])
        log_line(f"LLM二判失败汇总: {top_err}", logs_path)
    log_line(
        f"LLM二判汇总: total={len(top_items)}, ok={result.ok_count}, "
        f"fail={len(top_items) - result.ok_count}, route_hits={result.route_hits}",
        logs_path,
    )
    return result.decisions, len(top_items), result.ok_count, result.route_hits


def collect_llm_overlay_results(
    top_items: list[TailBuyCandidate],
    *,
    config: LlmOverlayConfig,
    llm_concurrency: int,
    logs_path: str | None,
) -> LlmOverlayRunResult:
    result = LlmOverlayRunResult()
    with ThreadPoolExecutor(max_workers=max(1, int(llm_concurrency))) as ex:
        futures = {ex.submit(judge_llm_overlay_candidate, item, config, logs_path): item.code for item in top_items}
        timeout_seconds = max(1, int(remaining_seconds(config.deadline_at)))
        try:
            _collect_finished_futures(futures, result, config, timeout_seconds, logs_path)
        except FutureTimeout:
            _cancel_deadline_futures(futures, result, config, logs_path)
    return result


def judge_llm_overlay_candidate(
    item: TailBuyCandidate,
    config: LlmOverlayConfig,
    logs_path: str | None,
) -> tuple[str, dict | None, str | None]:
    depth_info = config.depth_map.get(item.code)
    system_prompt, user_prompt = build_llm_prompt(item, style=config.style, depth_info=depth_info)
    last_err = ""
    for route in config.routes:
        left = remaining_seconds(config.deadline_at)
        if left <= 8:
            return item.code, None, "deadline_exceeded"
        route_name = route.get("name", "unknown")
        try:
            text = call_llm(
                provider=route["provider"],
                model=route["model"],
                api_key=route["api_key"],
                system_prompt=system_prompt,
                user_message=user_prompt,
                base_url=(route.get("base_url") or None),
                timeout=int(max(10, min(45, left - 4))),
                max_output_tokens=512,
                allow_truncated_text=True,
            )
            parsed = parse_llm_decision(text)
            if parsed:
                parsed["model_used"] = route_name
                return item.code, parsed, None
            last_err = f"{route_name}:llm_parse_failed"
        except Exception as exc:
            last_err = f"{route_name}:{exc}"
            if config.verbose_errors:
                log_line(f"LLM路由失败: code={item.code}, route={route_name}, err={exc}", logs_path)
    return item.code, None, last_err or "all_routes_failed"


def record_llm_overlay_payload(result: LlmOverlayRunResult, payload: dict) -> None:
    result.ok_count += 1
    route = str(payload.get("model_used", "") or "").strip() or "unknown"
    result.route_hits[route] = result.route_hits.get(route, 0) + 1


def _fetch_one_depth(client: TickFlowClient, code: str) -> tuple[str, dict | None]:
    try:
        depth = client.get_depth(code)
        bid_total = sum(depth.get("bid_volumes") or [])
        ask_total = sum(depth.get("ask_volumes") or [])
        total = bid_total + ask_total
        weibi = (bid_total - ask_total) / total * 100 if total > 0 else 0.0
        return code, {"bid_total": bid_total, "ask_total": ask_total, "weibi": round(weibi, 1)}
    except Exception:
        return code, None


def _collect_finished_futures(
    futures: dict,
    result: LlmOverlayRunResult,
    config: LlmOverlayConfig,
    timeout_seconds: int,
    logs_path: str | None,
) -> None:
    for fut in as_completed(futures, timeout=timeout_seconds):
        code = futures[fut]
        try:
            candidate_code, payload, err = fut.result()
            if payload:
                result.decisions[candidate_code] = payload
                record_llm_overlay_payload(result, payload)
            elif err:
                result.errors[str(err)] += 1
                if config.verbose_errors:
                    log_line(f"LLM二判失败: {code}, err={err}", logs_path)
        except Exception as exc:
            result.errors[f"FutureException:{type(exc).__name__}"] += 1
            if config.verbose_errors:
                log_line(f"LLM二判异常: {code}, err={exc}", logs_path)


def _cancel_deadline_futures(
    futures: dict,
    result: LlmOverlayRunResult,
    config: LlmOverlayConfig,
    logs_path: str | None,
) -> None:
    log_line("LLM 二判触发 deadline 保护：停止等待剩余结果。", logs_path)
    for fut, code in futures.items():
        if fut.done():
            continue
        fut.cancel()
        result.errors["deadline_cancelled"] += 1
        if config.verbose_errors:
            log_line(f"LLM二判取消: {code}", logs_path)
