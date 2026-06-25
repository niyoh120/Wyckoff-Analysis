"""Persistence helpers for daily job workflow outputs."""

from __future__ import annotations

import os
from datetime import datetime

from integrations.recommendation_payload import (
    mark_ai_recommendations,
    prepare_recommendation_payload,
    upsert_recommendation_payload,
    write_recommendation_backup_artifact,
)
from integrations.supabase_market_signal import upsert_market_signal_daily
from workflows.step4_pipeline import TZ, is_confirmed_step4_candidate


def persist_benchmark_context(
    benchmark_context: dict,
    logs_path: str | None,
    *,
    dry_run: bool,
    trade_date: str,
    log_fn,
) -> None:
    if not benchmark_context:
        return
    if dry_run:
        log_fn("预演模式: 跳过市场信号写库(benchmark)", logs_path)
        return
    payload = _benchmark_payload(benchmark_context)
    ok = upsert_market_signal_daily(trade_date, payload)
    log_fn(
        f"市场信号写库(benchmark): ok={ok}, trade_date={trade_date}, regime={payload.get('benchmark_regime')}",
        logs_path,
    )


def persist_recommendations(
    symbols_info: list[dict],
    logs_path: str | None,
    *,
    dry_run: bool,
    trade_date: str,
    log_fn,
) -> tuple[int | None, list[dict]]:
    write_symbols = recommendation_write_symbols(symbols_info)
    if dry_run:
        log_fn(
            f"预演模式: 跳过推荐记录入库 raw_count={len(symbols_info)}, write_count={len(write_symbols)}",
            logs_path,
        )
        return None, []
    try:
        recommend_date = int(trade_date.replace("-", ""))
        if not write_symbols:
            log_fn(f"推荐记录入库: raw_count={len(symbols_info)}, write_count=0（二次确认为空，跳过）", logs_path)
            return recommend_date, []
        payload = prepare_recommendation_payload(recommend_date, write_symbols)
        write_recommendation_backup(recommend_date, payload, logs_path, ai_codes=None, log_fn=log_fn)
        rec_ok = upsert_recommendation_payload(payload)
        log_fn(
            "推荐记录入库: "
            f"ok={rec_ok}, raw_count={len(symbols_info)}, write_count={len(write_symbols)}, "
            f"payload_count={len(payload)}, date={recommend_date}",
            logs_path,
        )
        return recommend_date, payload
    except Exception as e:
        log_fn(f"推荐记录入库失败: {e}", logs_path)
        return None, []


def recommendation_write_symbols(symbols_info: list[dict]) -> list[dict]:
    return [item for item in symbols_info if is_recommendation_write_candidate(item)]


def is_recommendation_write_candidate(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    return is_confirmed_step4_candidate(item)


def write_recommendation_backup(
    recommend_trade_date_int: int,
    payload: list[dict],
    logs_path: str | None,
    *,
    ai_codes: list[str] | None,
    log_fn,
) -> None:
    output_dir = os.getenv("DAILY_JOB_ARTIFACTS_DIR", "").strip()
    if not output_dir or not payload:
        return
    try:
        paths = write_recommendation_backup_artifact(
            recommend_trade_date_int,
            payload,
            output_dir,
            ai_codes=ai_codes,
        )
        if paths:
            log_fn(f"推荐记录备份 artifact: {', '.join(paths)}", logs_path)
    except Exception as e:
        log_fn(f"推荐记录备份 artifact 失败: {e}", logs_path)


def mark_step3_recommendations(
    recommend_trade_date_int: int | None,
    step3_springboard_codes: list[str],
    step3_springboard_updates: dict[str, dict] | None,
    logs_path: str | None,
    *,
    dry_run: bool,
    log_fn,
) -> None:
    if dry_run:
        log_fn("预演模式: 跳过推荐记录AI标记", logs_path)
        return
    if recommend_trade_date_int is None:
        return
    try:
        ai_mark_ok = mark_ai_recommendations(
            recommend_date=recommend_trade_date_int,
            ai_codes=step3_springboard_codes,
            springboard_updates=step3_springboard_updates,
        )
        log_fn(
            "推荐记录AI标记: "
            f"ok={ai_mark_ok}, date={recommend_trade_date_int}, ai_count={len(step3_springboard_codes)}",
            logs_path,
        )
    except Exception as e:
        log_fn(f"推荐记录AI标记失败: {e}", logs_path)


def persist_theme_radar(step2_details: dict, logs_path: str | None, *, dry_run: bool, log_fn) -> None:
    metrics = (step2_details or {}).get("metrics", {}) or {}
    snapshot = metrics.get("theme_radar_current") or metrics.get("theme_radar") or {}
    if dry_run or not snapshot:
        return
    try:
        from integrations.theme_radar_storage import persist_theme_radar_snapshot

        result = persist_theme_radar_snapshot(snapshot, local_fallback=False)
        log_fn(
            f"主题雷达写库: supabase={result.get('supabase', 0)}, sqlite={result.get('sqlite', 0)}",
            logs_path,
        )
    except Exception as exc:
        log_fn(f"主题雷达写库失败: {exc}", logs_path)


def _benchmark_payload(benchmark_context: dict) -> dict:
    return {
        "benchmark_regime": str(benchmark_context.get("regime", "") or "").strip().upper() or None,
        "main_index_code": str(benchmark_context.get("main_code", "000001") or "000001").strip(),
        "main_index_close": benchmark_context.get("close"),
        "main_index_ma50": benchmark_context.get("ma50"),
        "main_index_ma200": benchmark_context.get("ma200"),
        "main_index_recent3_cum_pct": benchmark_context.get("recent3_cum_pct"),
        "main_index_today_pct": benchmark_context.get("main_today_pct"),
        "smallcap_index_code": str(benchmark_context.get("smallcap_code", "") or "").strip() or None,
        "smallcap_close": benchmark_context.get("smallcap_close"),
        "smallcap_recent3_cum_pct": benchmark_context.get("smallcap_recent3_cum_pct"),
        "source_jobs": {"daily_job": {"updated_at": datetime.now(TZ).isoformat(), "writer": "step2_benchmark_context"}},
    }
