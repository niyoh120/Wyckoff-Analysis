"""
TickFlow 港股/美股 Wyckoff 漏斗任务。

流程：标的池实时行情 -> 流动性预筛 -> 批量历史日 K -> Wyckoff 漏斗。
结果写入本地 artifact / GitHub Summary；US/HK 生产任务会写推荐表供 Web 复盘页读取。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

if __name__ == "__main__" or not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.wyckoff_engine import (
    FunnelConfig,
    detect_leader_radar,
    layer1_filter,
    layer2_strength_detailed,
    layer3_sector_resonance,
    layer4_triggers,
    normalize_hist_from_fetch,
)
from integrations.tickflow_client import TickFlowClient
from integrations.tickflow_notice import TICKFLOW_UPGRADE_URL
from tools.candidate_ranker import TRIGGER_LABELS


@dataclass(frozen=True)
class MarketSpec:
    key: str
    label: str
    universe: str
    symbol_file: str
    benchmark_symbols: tuple[str, ...]
    default_max_symbols: int
    default_min_quote_amount: float
    default_min_quote_price: float


@dataclass(frozen=True)
class RuntimeConfig:
    spec: MarketSpec
    max_symbols: int
    quote_batch_size: int
    quote_batch_sleep: float
    kline_count: int
    kline_batch_size: int
    kline_batch_sleep: float
    min_quote_amount: float
    min_quote_price: float
    min_avg_amount: float
    min_history_rows: int
    output_path: Path | None
    symbol_path: Path
    benchmark_symbols: tuple[str, ...]


MARKET_SPECS = {
    "hk": MarketSpec(
        key="hk",
        label="港股",
        universe="HK_Equity",
        symbol_file="hk.txt",
        benchmark_symbols=("800000.HK", "HSI.HK", "^HSI", "HSI"),
        default_max_symbols=600,
        default_min_quote_amount=2_000_000.0,
        default_min_quote_price=1.0,
    ),
    "us": MarketSpec(
        key="us",
        label="美股",
        universe="US_Equity",
        symbol_file="us.txt",
        benchmark_symbols=("SPY.US", "QQQ.US"),
        default_max_symbols=1500,
        default_min_quote_amount=5_000_000.0,
        default_min_quote_price=1.0,
    ),
    "etf": MarketSpec(
        key="etf",
        label="ETF",
        universe="CN_Fund",
        symbol_file="etf_cn.txt",
        benchmark_symbols=(),
        default_max_symbols=200,
        default_min_quote_amount=500_000.0,
        default_min_quote_price=0.0,
    ),
}


def _int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(default, minimum)
    try:
        return max(int(raw), minimum)
    except ValueError:
        return max(default, minimum)


def _float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(default, minimum)
    try:
        return max(float(raw), minimum)
    except ValueError:
        return max(default, minimum)


def _benchmark_symbols(spec: MarketSpec) -> tuple[str, ...]:
    raw = (
        os.getenv(f"MARKET_FUNNEL_{spec.key.upper()}_BENCHMARK_SYMBOLS", "").strip()
        or os.getenv("MARKET_FUNNEL_BENCHMARK_SYMBOLS", "").strip()
    )
    if not raw:
        return spec.benchmark_symbols
    return tuple(symbol.strip().upper() for symbol in raw.replace(";", ",").split(",") if symbol.strip())


def _runtime_config(market: str, output: str | None) -> RuntimeConfig:
    spec = MARKET_SPECS[market]
    symbol_file = (
        os.getenv(f"MARKET_FUNNEL_{market.upper()}_SYMBOL_FILE", "").strip()
        or os.getenv("MARKET_FUNNEL_SYMBOL_FILE", "").strip()
    )
    symbol_path = (
        Path(symbol_file)
        if symbol_file
        else Path(__file__).resolve().parents[1] / "data" / "market_universes" / spec.symbol_file
    )
    return RuntimeConfig(
        spec=spec,
        max_symbols=_int_env("MARKET_FUNNEL_MAX_SYMBOLS", spec.default_max_symbols, minimum=1),
        quote_batch_size=_int_env("MARKET_FUNNEL_QUOTE_BATCH_SIZE", 500, minimum=1),
        quote_batch_sleep=_float_env("MARKET_FUNNEL_QUOTE_BATCH_SLEEP", 0.25),
        kline_count=_int_env("MARKET_FUNNEL_KLINE_COUNT", 320, minimum=220),
        kline_batch_size=_int_env("MARKET_FUNNEL_KLINE_BATCH_SIZE", 200, minimum=1),
        kline_batch_sleep=_float_env("MARKET_FUNNEL_KLINE_BATCH_SLEEP", 0.55),
        min_quote_amount=_float_env("MARKET_FUNNEL_MIN_QUOTE_AMOUNT", spec.default_min_quote_amount),
        min_quote_price=_float_env("MARKET_FUNNEL_MIN_QUOTE_PRICE", spec.default_min_quote_price),
        min_avg_amount=_float_env("MARKET_FUNNEL_MIN_AVG_AMOUNT", 0.0),
        min_history_rows=_int_env("MARKET_FUNNEL_MIN_HISTORY_ROWS", 220, minimum=80),
        output_path=Path(output) if output else None,
        symbol_path=symbol_path,
        benchmark_symbols=_benchmark_symbols(spec),
    )


def _load_symbols(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"market symbol file not found: {path}")
    seen: set[str] = set()
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].replace(",", " ").strip()
        for raw in clean.split():
            symbol = raw.strip().upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
    if not symbols:
        raise ValueError(f"market symbol file is empty: {path}")
    return symbols


def _row_float(row: dict[str, Any], *keys: str) -> float | None:
    ext = row.get("ext") if isinstance(row.get("ext"), dict) else {}
    for key in keys:
        value = row.get(key)
        if value is None and key.startswith("ext."):
            value = ext.get(key.split(".", 1)[1])
        try:
            if value is not None and pd.notna(value):
                return float(value)
        except Exception:
            continue
    return None


def _quote_change_pct(row: dict[str, Any]) -> float:
    direct = _row_float(row, "change_pct", "ext.change_pct")
    if direct is not None:
        return direct
    last_price = _row_float(row, "last_price", "close")
    prev_close = _row_float(row, "prev_close")
    if last_price is None or prev_close is None or prev_close <= 0:
        return 0.0
    return (last_price / prev_close - 1.0) * 100.0


def _quote_name(row: dict[str, Any], symbol: str) -> str:
    ext = row.get("ext") if isinstance(row.get("ext"), dict) else {}
    for value in (row.get("name"), row.get("ext.name"), ext.get("name")):
        text = str(value or "").strip()
        if text:
            return text
    return symbol


def _quote_sector(row: dict[str, Any]) -> str:
    ext = row.get("ext") if isinstance(row.get("ext"), dict) else {}
    keys = ("sector", "industry", "sector_name", "industry_name", "gics_sector", "ext.sector", "ext.industry")
    for key in keys:
        value = row.get(key)
        if value is None and key.startswith("ext."):
            value = ext.get(key.split(".", 1)[1])
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _rank_quotes(
    quotes: dict[str, dict[str, Any]],
    *,
    max_symbols: int,
    min_quote_amount: float,
    min_quote_price: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, row in quotes.items():
        last_price = _row_float(row, "last_price", "close")
        if last_price is None or last_price <= 0:
            continue
        if last_price < min_quote_price:
            continue
        amount = _row_float(row, "amount") or 0.0
        if amount < min_quote_amount:
            continue
        sector = _quote_sector(row)
        rows.append(
            {
                "symbol": symbol,
                "name": _quote_name(row, symbol),
                "last_price": float(last_price),
                "amount": float(amount),
                "volume": float(_row_float(row, "volume") or 0.0),
                "change_pct": float(_quote_change_pct(row)),
                "sector": sector,
            }
        )
    rows.sort(key=lambda item: (item["amount"], item["volume"]), reverse=True)
    return rows[:max_symbols]


def _chunks(items: list[str], size: int) -> list[list[str]]:
    width = max(int(size), 1)
    return [items[i : i + width] for i in range(0, len(items), width)]


def _fetch_quotes(
    client: TickFlowClient,
    symbols: list[str],
    cfg: RuntimeConfig,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    batches = _chunks(symbols, cfg.quote_batch_size)
    for index, chunk in enumerate(batches, start=1):
        print(f"[market-funnel] {cfg.spec.label} 行情批次 {index}/{len(batches)} symbols={len(chunk)}")
        out.update(client.get_quotes(symbols=chunk))
        if index < len(batches) and cfg.quote_batch_sleep > 0:
            time.sleep(cfg.quote_batch_sleep)
    return out


def _fetch_daily_histories(
    client: TickFlowClient,
    symbols: list[str],
    cfg: RuntimeConfig,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    started = time.monotonic()
    out: dict[str, pd.DataFrame] = {}
    batches = _chunks(symbols, cfg.kline_batch_size)
    for index, chunk in enumerate(batches, start=1):
        print(f"[market-funnel] {cfg.spec.label} 日K批次 {index}/{len(batches)} symbols={len(chunk)}")
        batch = client.get_klines_batch(chunk, period="1d", count=cfg.kline_count, adjust="forward")
        for symbol, df in batch.items():
            norm = normalize_hist_from_fetch(df)
            if norm is not None and len(norm) >= cfg.min_history_rows:
                out[symbol] = norm
        if index < len(batches) and cfg.kline_batch_sleep > 0:
            time.sleep(cfg.kline_batch_sleep)
    elapsed = time.monotonic() - started
    stats = {
        "requested": len(symbols),
        "fetched": len(out),
        "failed": max(len(symbols) - len(out), 0),
        "batches": len(batches),
        "elapsed_s": round(elapsed, 2),
        "qps": round(len(out) / elapsed, 3) if elapsed > 0 else 0.0,
    }
    return out, stats


def _fetch_benchmark_history(client: TickFlowClient, cfg: RuntimeConfig) -> tuple[pd.DataFrame | None, str]:
    for symbol in cfg.benchmark_symbols:
        try:
            if hasattr(client, "get_klines"):
                raw = client.get_klines(symbol, period="1d", count=cfg.kline_count, adjust="forward")
            else:
                raw = client.get_klines_batch([symbol], period="1d", count=cfg.kline_count, adjust="forward").get(
                    symbol
                )
            norm = normalize_hist_from_fetch(raw) if raw is not None else None
            if norm is not None and len(norm) >= 60:
                print(f"[market-funnel] benchmark loaded: {symbol} rows={len(norm)}")
                return norm, symbol
        except Exception as exc:
            print(f"[market-funnel] benchmark fetch failed: {symbol}: {exc}")
    return None, ""


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


def funnel_config_for_market(market: str, *, trading_days: int = 320, min_avg_amount: float = 0.0) -> FunnelConfig:
    funnel_cfg = FunnelConfig(trading_days=trading_days)
    funnel_cfg.require_cn_main_or_chinext = False
    funnel_cfg.min_market_cap_yi = 0.0
    funnel_cfg.min_avg_amount_wan = min_avg_amount / 10000.0
    funnel_cfg.enable_rs_filter = True
    funnel_cfg.enable_rs_divergence_channel = True
    funnel_cfg.require_bench_latest_alignment = False

    if market == "us":
        funnel_cfg.sos_pct_min = 8.0
        funnel_cfg.sos_vol_ratio = 3.2
        funnel_cfg.spring_vol_ratio = 1.3
        funnel_cfg.evr_max_rise = 3.0
    elif market == "hk":
        funnel_cfg.sos_pct_min = 7.0
        funnel_cfg.sos_vol_ratio = 3.0
        funnel_cfg.spring_tr_max_range_pct = 25.0
        funnel_cfg.global_entry_max_bias_200 = 25.0
        funnel_cfg.accum_price_from_low_max = 0.40
        funnel_cfg.evr_min_turnover = 0.3
    elif market == "etf":
        funnel_cfg.sos_pct_min = 3.5
        funnel_cfg.sos_vol_ratio = 2.0
        funnel_cfg.spring_vol_ratio = 1.0
        funnel_cfg.evr_min_turnover = 0.3
        funnel_cfg.evr_max_rise = 2.0

    return funnel_cfg


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
    leader_rows = detect_leader_radar(layer1, df_map, sector_map, channel_map, funnel_cfg)
    metrics = {
        "layer1": len(layer1),
        "layer2": len(layer2),
        "layer3": len(layer3),
        "total_hits": sum(len(items) for items in triggers.values()),
        "by_trigger": {key: len(items) for key, items in triggers.items()},
        "leader_radar": len(leader_rows),
        "leader_radar_rows": leader_rows,
        "leader_radar_symbols": [str(row["code"]) for row in leader_rows],
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
            item["score"] = float(item["score"]) + float(score)
            item["triggers"].append(TRIGGER_LABELS.get(trigger, trigger))
    out = list(rows.values())
    for item in out:
        latest_close, latest_trade_date = _latest_history_snapshot(df_map.get(str(item["symbol"])))
        item["latest_close"] = latest_close
        if latest_trade_date is not None:
            item["latest_trade_date"] = latest_trade_date
    out.sort(key=lambda item: float(item["score"]), reverse=True)
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


def _report_path(output_path: Path | None) -> Path | None:
    if output_path is None:
        return None
    if output_path.name.endswith("_result.json"):
        return output_path.with_name(output_path.name.replace("_result.json", "_report.md"))
    return output_path.with_suffix(".md")


def _fmt_number(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_float(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _leader_radar_markdown_block(metrics: dict[str, Any]) -> list[str]:
    rows = []
    for index, item in enumerate((metrics.get("leader_radar_rows") or [])[:30], start=1):
        rows.append(
            "| "
            f"{index} | {item.get('code', '-')} | {_fmt_float(item.get('score'))} | "
            f"{_fmt_float(item.get('ret20'))}% | {_fmt_float(item.get('ret60'))}% | "
            f"{_fmt_float(item.get('ret120'))}% | {item.get('risk', '-')} |"
        )
    return [
        "## 龙头雷达",
        "独立主升观察池，不计入正式 L4 买点。",
        "| # | 代码 | 分数 | 20日 | 60日 | 120日 | 风险 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- |",
        *(rows or ["| - | - | - | - | - | - | 本次无主升雷达候选 |"]),
        "",
    ]


def _render_markdown_report(result: dict[str, Any]) -> str:
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    rows = [
        ("股票池", result.get("universe_symbol_count")),
        ("实时行情返回", result.get("quote_count")),
        ("流动性预筛", result.get("selected_count")),
        ("日K可用", result.get("fetched_count")),
        ("L1 基础结构", metrics.get("layer1")),
        ("L2 强弱通道", metrics.get("layer2")),
        ("L3 板块共振", metrics.get("layer3")),
        ("L4 触发命中", metrics.get("total_hits")),
    ]
    trigger_rows = []
    for key, count in (metrics.get("by_trigger") or {}).items():
        trigger_rows.append(f"| {TRIGGER_LABELS.get(str(key), str(key))} | {_fmt_number(count)} |")
    candidates = result.get("top_candidates") if isinstance(result.get("top_candidates"), list) else []
    candidate_rows = []
    for index, item in enumerate(candidates[:30], start=1):
        triggers = " / ".join(str(x) for x in item.get("triggers", [])) or "-"
        candidate_rows.append(
            "| "
            f"{index} | {item.get('symbol', '-')} | {item.get('name', '-')} | "
            f"{_fmt_float(item.get('score'))} | {_fmt_float(item.get('latest_close'), 3)} | {triggers} |"
        )
    blocks = [
        f"# Wyckoff Funnel {result.get('label', result.get('market', ''))} 最终报告",
        "## 漏斗概览",
        "| 阶段 | 数量 |",
        "| --- | ---: |",
        *[f"| {name} | {_fmt_number(value)} |" for name, value in rows],
        "",
        "## 触发分布",
        "| 触发 | 数量 |",
        "| --- | ---: |",
        *(trigger_rows or ["| 无触发 | 0 |"]),
        "",
        "## Top 候选",
        "| # | 代码 | 名称 | 分数 | 最新收盘 | 触发 |",
        "| ---: | --- | --- | ---: | ---: | --- |",
        *(candidate_rows or ["| - | - | - | - | - | 本次无 L4 触发候选 |"]),
        "",
        *_leader_radar_markdown_block(metrics),
        "## 运行参数",
        f"- 股票池文件: `{result.get('symbol_file', '-')}`",
        f"- 实时行情: `{result.get('limits', {}).get('quote_batch_size', '-')}` 标的/批, "
        f"sleep `{result.get('limits', {}).get('quote_batch_sleep', '-')}`s",
        f"- 日K批量: `{result.get('limits', {}).get('kline_batch_size', '-')}` 标的/批, "
        f"sleep `{result.get('limits', {}).get('kline_batch_sleep', '-')}`s",
        f"- 成交额门槛: `{_fmt_number(result.get('limits', {}).get('min_quote_amount'))}`",
    ]
    return "\n".join(blocks).rstrip() + "\n"


def _write_output(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[market-funnel] result written: {path}")


def _write_report(path: Path | None, result: dict[str, Any]) -> None:
    report = _render_markdown_report(result)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"[market-funnel] report written: {path}")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as fh:
            fh.write(report + "\n")


def _require_tickflow_client() -> TickFlowClient:
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(f"market_funnel_job 需要实时行情数据，请购买 TickFlow：{TICKFLOW_UPGRADE_URL}")
    return TickFlowClient(api_key=api_key)


def _candidate_trade_date(candidate: dict[str, Any]) -> int | None:
    try:
        date_int = int(candidate.get("latest_trade_date"))
    except (TypeError, ValueError):
        return None
    return date_int if 19000101 <= date_int <= 29991231 else None


def _tracking_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(candidate.get("symbol", "")).strip(),
        "name": str(candidate.get("name", "")).strip(),
        "tag": ",".join(candidate.get("triggers") or []),
        "score": float(candidate.get("score") or 0),
        "latest_close": float(candidate.get("latest_close") or 0),
    }


def _upsert_funnel_to_tracking(candidates: list[dict[str, Any]], market: str) -> None:
    if not candidates or market not in ("us", "hk"):
        return
    from integrations.supabase_recommendation import upsert_global_recommendations

    rows_by_date: dict[int, list[dict[str, Any]]] = {}
    skipped = 0
    for candidate in candidates:
        recommend_date = _candidate_trade_date(candidate)
        if recommend_date is None:
            skipped += 1
            continue
        rows_by_date.setdefault(recommend_date, []).append(_tracking_row(candidate))
    if not rows_by_date:
        raise ValueError("cannot resolve recommendation trade date from market histories")
    for recommend_date, rows in sorted(rows_by_date.items()):
        ok = upsert_global_recommendations(recommend_date, rows, market)
        print(f"[market-funnel] DB write: market={market}, date={recommend_date}, candidates={len(rows)}, ok={ok}")
        if not ok:
            raise RuntimeError(f"DB write failed for market={market}, candidates={len(rows)}")
    if skipped:
        print(f"[market-funnel] DB write skipped candidates without trade date: {skipped}/{len(candidates)}")


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
        "top_leader_radar": (metrics.get("leader_radar_rows") or [])[:100],
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


def _write_tracking_candidates_if_enabled(candidates: list[dict[str, Any]], market: str) -> None:
    if os.getenv("MARKET_FUNNEL_WRITE_DB", "").strip().lower() in {"1", "true", "yes"}:
        _upsert_funnel_to_tracking(candidates, market)


def _fetch_market_inputs(
    tf: TickFlowClient,
    universe_symbols: list[str],
    runtime: RuntimeConfig,
) -> tuple[
    dict[str, dict[str, Any]], list[dict[str, Any]], pd.DataFrame | None, str, dict[str, pd.DataFrame], dict[str, Any]
]:
    quotes = _fetch_quotes(tf, universe_symbols, runtime)
    ranked = _rank_quotes(
        quotes,
        max_symbols=runtime.max_symbols,
        min_quote_amount=runtime.min_quote_amount,
        min_quote_price=runtime.min_quote_price,
    )
    if not ranked and runtime.min_quote_amount > 0:
        print("[market-funnel] quote amount filter returned empty; retry ranking without amount floor")
        ranked = _rank_quotes(
            quotes,
            max_symbols=runtime.max_symbols,
            min_quote_amount=0.0,
            min_quote_price=runtime.min_quote_price,
        )
    symbols = [str(item["symbol"]) for item in ranked]
    bench_df, bench_symbol = _fetch_benchmark_history(tf, runtime)
    df_map, fetch_stats = _fetch_daily_histories(tf, symbols, runtime)
    return quotes, ranked, bench_df, bench_symbol, df_map, fetch_stats


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
    runtime = _runtime_config(market, output)
    tf = client or _require_tickflow_client()
    universe_symbols = _load_symbols(runtime.symbol_path)
    print(
        f"[market-funnel] start market={runtime.spec.key} universe={runtime.spec.universe} "
        f"symbols={len(universe_symbols)} max_symbols={runtime.max_symbols} "
        f"quote_batch={runtime.quote_batch_size} quote_sleep={runtime.quote_batch_sleep} "
        f"kline_batch={runtime.kline_batch_size} "
        f"symbol_file={runtime.symbol_path}"
    )
    quotes, ranked, bench_df, bench_symbol, df_map, fetch_stats = _fetch_market_inputs(tf, universe_symbols, runtime)
    symbols = [str(item["symbol"]) for item in ranked]
    report_path = _report_path(runtime.output_path)
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
    _write_output(runtime.output_path, result)
    _write_report(report_path, result)
    _write_tracking_candidates_if_enabled(candidates, runtime.spec.key)
    print(
        f"[market-funnel] done ok={result['ok']} market={runtime.spec.key} "
        f"quotes={len(quotes)} selected={len(symbols)} fetched={len(df_map)} "
        f"hits={metrics.get('total_hits', 0) if metrics else 0}"
    )
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TickFlow HK/US Wyckoff funnel job.")
    parser.add_argument("--market", choices=sorted(MARKET_SPECS), required=True)
    parser.add_argument("--output", default="", help="Optional JSON result path.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_market_funnel(args.market, output=args.output or None)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
