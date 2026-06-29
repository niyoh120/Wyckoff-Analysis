"""
TickFlow 港股/美股 Wyckoff 漏斗工作流。

流程：标的池实时行情 -> 流动性预筛 -> 批量历史日 K -> Wyckoff 漏斗。
结果写入本地 artifact / GitHub Summary；US/HK 生产任务会写推荐表供 Web 复盘页读取。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from core.candidate_policy import candidate_score_value
from core.candidate_ranker import TRIGGER_LABELS
from core.wyckoff_engine import (
    FunnelConfig,
    detect_leader_radar,
    layer1_filter,
    layer2_strength_detailed,
    layer3_sector_resonance,
    layer4_triggers,
)
from integrations.tickflow_client import TickFlowClient
from integrations.tickflow_notice import TICKFLOW_UPGRADE_URL
from workflows.market_funnel_config import funnel_config_for_market
from workflows.market_funnel_data import fetch_market_inputs, load_market_symbols
from workflows.market_funnel_report import (
    market_funnel_report_path,
    write_market_funnel_output,
    write_market_funnel_report,
)
from workflows.market_funnel_runtime import MARKET_SPECS, RuntimeConfig, runtime_config_from_env
from workflows.market_funnel_tracking import write_tracking_candidates_if_enabled

MARKET_CHOICES = tuple(sorted(MARKET_SPECS))


def _market_regime_context(bench_df: pd.DataFrame | None, cfg: FunnelConfig) -> dict[str, Any]:
    context: dict[str, Any] = {"available": False, "regime": "UNKNOWN", "candidate_cap": None}
    if bench_df is None or bench_df.empty or len(bench_df) < 60:
        return context
    work = bench_df.sort_values("date").copy()
    close = pd.to_numeric(work.get("close"), errors="coerce")
    pct = pd.to_numeric(work.get("pct_chg"), errors="coerce")
    if close.dropna().empty:
        return context
    ma50 = close.rolling(50).mean().iloc[-1]
    ma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else float("nan")
    recent3 = pct.dropna().tail(3)
    today_pct = float(recent3.iloc[-1]) if not recent3.empty else None
    recent3_cum = float(((recent3 / 100.0 + 1.0).prod() - 1.0) * 100.0) if not recent3.empty else None
    regime = _classify_benchmark_regime(float(close.iloc[-1]), ma50, ma200, today_pct, recent3_cum)
    _tune_funnel_for_regime(cfg, regime)
    context.update(
        {
            "available": True,
            "regime": regime,
            "close": round(float(close.iloc[-1]), 4),
            "ma50": None if pd.isna(ma50) else round(float(ma50), 4),
            "ma200": None if pd.isna(ma200) else round(float(ma200), 4),
            "today_pct": today_pct,
            "recent3_cum_pct": recent3_cum,
            "candidate_cap": 0 if regime == "CRASH" else 30 if regime == "RISK_OFF" else None,
        }
    )
    return context


def _classify_benchmark_regime(
    close: float,
    ma50: float,
    ma200: float,
    today_pct: float | None,
    recent3_cum: float | None,
) -> str:
    if today_pct is not None and today_pct <= -3.5:
        return "CRASH"
    if recent3_cum is not None and recent3_cum <= -6.0:
        return "CRASH"
    if pd.notna(ma200) and pd.notna(ma50) and close < ma200 and ma50 < ma200 and (recent3_cum or 0.0) <= -2.0:
        return "RISK_OFF"
    if pd.notna(ma200) and pd.notna(ma50) and close > ma50 > ma200 and (recent3_cum or 0.0) >= 0.0:
        return "RISK_ON"
    return "NEUTRAL"


def _tune_funnel_for_regime(cfg: FunnelConfig, regime: str) -> None:
    if regime == "CRASH":
        cfg.rps_fast_min = max(cfg.rps_fast_min, 85.0)
        cfg.rps_slow_min = max(cfg.rps_slow_min, 80.0)
        cfg.rs_min_long = max(cfg.rs_min_long, 4.0)
        cfg.rs_min_short = max(cfg.rs_min_short, 1.0)
    elif regime == "RISK_OFF":
        cfg.rps_fast_min = max(cfg.rps_fast_min, 80.0)
        cfg.rps_slow_min = max(cfg.rps_slow_min, 75.0)
        cfg.rs_min_long = max(cfg.rs_min_long, 3.0)
        cfg.rs_min_short = max(cfg.rs_min_short, 1.0)


def _funnel_config(cfg: RuntimeConfig) -> FunnelConfig:
    return funnel_config_for_market(
        cfg.spec.key,
        trading_days=cfg.kline_count,
        min_avg_amount=cfg.min_avg_amount,
    )


def _run_layers(
    symbols: list[str],
    name_map: dict[str, str],
    df_map: dict[str, pd.DataFrame],
    cfg: RuntimeConfig,
    bench_df: pd.DataFrame | None = None,
    sector_map: dict[str, str] | None = None,
) -> tuple[dict[str, list[tuple[str, float]]], dict[str, Any]]:
    funnel_cfg = _funnel_config(cfg)
    benchmark_context = _market_regime_context(bench_df, funnel_cfg)
    layer1 = layer1_filter(symbols, name_map, {}, df_map, funnel_cfg)
    layer2, channel_map, _ = layer2_strength_detailed(layer1, df_map, bench_df, funnel_cfg, rps_universe=symbols)
    sector_map = sector_map or {}
    layer3, top_sectors = layer3_sector_resonance(layer2, sector_map, funnel_cfg, base_symbols=layer1, df_map=df_map)
    triggers = layer4_triggers(layer3, df_map, funnel_cfg, channel_map=channel_map)
    trend_watch_rows = detect_leader_radar(layer1, df_map, sector_map, channel_map, funnel_cfg)
    metrics = {
        "layer1": len(layer1),
        "layer2": len(layer2),
        "layer3": len(layer3),
        "total_hits": sum(len(items) for items in triggers.values()),
        "by_trigger": {key: len(items) for key, items in triggers.items()},
        "trend_watch": len(trend_watch_rows),
        "trend_watch_rows": trend_watch_rows,
        "trend_watch_symbols": [str(row["code"]) for row in trend_watch_rows],
        "top_sectors": top_sectors,
        "layer2_channel_map": channel_map,
        "benchmark": benchmark_context,
        "sector_coverage": sum(1 for symbol in layer2 if sector_map.get(symbol)),
    }
    return triggers, metrics


def _latest_history_snapshot(df: pd.DataFrame | None) -> tuple[float | None, int | None]:
    if df is None or df.empty or "close" not in df.columns:
        return (None, None)
    if "date" in df.columns:
        work = df[["date", "close"]].copy()
        work["date"] = pd.to_datetime(work["date"], errors="coerce")
        work["close"] = pd.to_numeric(work["close"], errors="coerce")
        work = work.dropna(subset=["date", "close"])
        work = work[work["close"] > 0].sort_values("date")
        if not work.empty:
            latest = work.iloc[-1]
            return (float(latest["close"]), int(latest["date"].strftime("%Y%m%d")))
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    return (float(close.iloc[-1]), None) if not close.empty else (None, None)


def _candidate_rows(
    triggers: dict[str, list[tuple[str, float]]],
    *,
    name_map: dict[str, str],
    df_map: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for trigger, hits in triggers.items():
        for symbol, score in hits:
            item = rows.setdefault(
                symbol,
                {"symbol": symbol, "name": name_map.get(symbol, symbol), "score": 0.0, "triggers": []},
            )
            item["score"] = candidate_score_value(item["score"]) + candidate_score_value(score)
            item["triggers"].append(TRIGGER_LABELS.get(trigger, trigger))
    out = list(rows.values())
    for item in out:
        latest_close, latest_trade_date = _latest_history_snapshot(df_map.get(str(item["symbol"])))
        item["latest_close"] = latest_close
        if latest_trade_date is not None:
            item["latest_trade_date"] = latest_trade_date
    out.sort(key=lambda item: candidate_score_value(item.get("score")), reverse=True)
    return out


def _sector_map_from_ranked(ranked: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item.get("symbol")): str(item.get("sector")).strip()
        for item in ranked
        if str(item.get("symbol") or "").strip() and str(item.get("sector") or "").strip()
    }


def _cap_candidates_for_regime(candidates: list[dict[str, Any]], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    benchmark = metrics.get("benchmark") if isinstance(metrics.get("benchmark"), dict) else {}
    cap = benchmark.get("candidate_cap")
    if cap is None:
        return candidates
    limit = max(int(cap), 0)
    return candidates[:limit]


def _require_tickflow_client() -> TickFlowClient:
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(f"market_funnel_job 需要实时行情数据，请购买 TickFlow：{TICKFLOW_UPGRADE_URL}")
    return TickFlowClient(api_key=api_key)


def _build_funnel_result(
    runtime: RuntimeConfig,
    universe_symbols: list[str],
    quotes: dict[str, dict[str, Any]],
    symbols: list[str],
    df_map: dict[str, pd.DataFrame],
    fetch_stats: dict[str, Any],
    metrics: dict[str, Any],
    candidates: list[dict[str, Any]],
    report_path: Path | None,
) -> dict[str, Any]:
    return {
        "ok": bool(quotes and df_map),
        "market": runtime.spec.key,
        "label": runtime.spec.label,
        "universe": runtime.spec.universe,
        "symbol_file": str(runtime.symbol_path),
        "report_path": str(report_path) if report_path else "",
        "universe_symbol_count": len(universe_symbols),
        "quote_count": len(quotes),
        "selected_count": len(symbols),
        "fetched_count": len(df_map),
        "fetch_stats": fetch_stats,
        "metrics": metrics,
        "top_candidates": candidates[:100],
        "top_trend_watch": (metrics.get("trend_watch_rows") or [])[:100],
        "limits": {
            "max_symbols": runtime.max_symbols,
            "quote_batch_size": runtime.quote_batch_size,
            "quote_batch_sleep": runtime.quote_batch_sleep,
            "kline_batch_size": runtime.kline_batch_size,
            "kline_batch_sleep": runtime.kline_batch_sleep,
            "min_quote_amount": runtime.min_quote_amount,
            "min_quote_price": runtime.min_quote_price,
        },
    }


def _run_funnel_for_ranked(
    ranked: list[dict[str, Any]],
    df_map: dict[str, pd.DataFrame],
    runtime: RuntimeConfig,
    bench_df: pd.DataFrame | None,
    bench_symbol: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    symbols = [str(item["symbol"]) for item in ranked]
    fetched_symbols = [symbol for symbol in symbols if symbol in df_map]
    name_map = {str(item["symbol"]): str(item["name"]) for item in ranked}
    sector_map = _sector_map_from_ranked(ranked)
    print(f"[market-funnel] {runtime.spec.label} 漏斗筛选 L1~L4 symbols={len(fetched_symbols)}")
    triggers, metrics = (
        _run_layers(fetched_symbols, name_map, df_map, runtime, bench_df=bench_df, sector_map=sector_map)
        if df_map
        else ({}, {})
    )
    if metrics and bench_symbol:
        metrics["benchmark_symbol"] = bench_symbol
    raw_candidates = _candidate_rows(triggers, name_map=name_map, df_map=df_map)
    candidates = _cap_candidates_for_regime(raw_candidates, metrics)
    if len(candidates) < len(raw_candidates):
        print(f"[market-funnel] regime cap: kept={len(candidates)}/{len(raw_candidates)}")
    return metrics, candidates


def run_market_funnel(
    market: str,
    *,
    output: str | None = None,
    client: TickFlowClient | None = None,
) -> dict[str, Any]:
    runtime = runtime_config_from_env(market, output)
    tf = client or _require_tickflow_client()
    universe_symbols = load_market_symbols(runtime.symbol_path)
    print(
        f"[market-funnel] start market={runtime.spec.key} universe={runtime.spec.universe} "
        f"symbols={len(universe_symbols)} max_symbols={runtime.max_symbols} "
        f"quote_batch={runtime.quote_batch_size} quote_sleep={runtime.quote_batch_sleep} "
        f"kline_batch={runtime.kline_batch_size} "
        f"symbol_file={runtime.symbol_path}"
    )
    quotes, ranked, bench_df, bench_symbol, df_map, fetch_stats = fetch_market_inputs(tf, universe_symbols, runtime)
    symbols = [str(item["symbol"]) for item in ranked]
    report_path = market_funnel_report_path(runtime.output_path)
    metrics, candidates = _run_funnel_for_ranked(ranked, df_map, runtime, bench_df, bench_symbol)
    result = _build_funnel_result(
        runtime,
        universe_symbols,
        quotes,
        symbols,
        df_map,
        fetch_stats,
        metrics,
        candidates,
        report_path,
    )
    write_market_funnel_output(runtime.output_path, result)
    write_market_funnel_report(report_path, result)
    write_tracking_candidates_if_enabled(candidates, runtime.spec.key)
    print(
        f"[market-funnel] done ok={result['ok']} market={runtime.spec.key} "
        f"quotes={len(quotes)} selected={len(symbols)} fetched={len(df_map)} "
        f"hits={metrics.get('total_hits', 0) if metrics else 0}"
    )
    return result
