"""
TickFlow 港股/美股 Wyckoff 漏斗任务。

流程：标的池实时行情 -> 流动性预筛 -> 批量历史日 K -> Wyckoff 漏斗。
结果仅写入本地 JSON artifact，不写数据库。
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
    layer1_filter,
    layer2_strength_detailed,
    layer3_sector_resonance,
    layer4_triggers,
    normalize_hist_from_fetch,
)
from integrations.tickflow_client import TickFlowClient
from tools.candidate_ranker import TRIGGER_LABELS


@dataclass(frozen=True)
class MarketSpec:
    key: str
    label: str
    universe: str
    default_max_symbols: int
    default_min_quote_amount: float


@dataclass(frozen=True)
class RuntimeConfig:
    spec: MarketSpec
    max_symbols: int
    kline_count: int
    kline_batch_size: int
    kline_batch_sleep: float
    min_quote_amount: float
    min_avg_amount: float
    min_history_rows: int
    output_path: Path | None


MARKET_SPECS = {
    "hk": MarketSpec(
        key="hk",
        label="港股",
        universe="HK_Equity",
        default_max_symbols=600,
        default_min_quote_amount=2_000_000.0,
    ),
    "us": MarketSpec(
        key="us",
        label="美股",
        universe="US_Equity",
        default_max_symbols=800,
        default_min_quote_amount=5_000_000.0,
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


def _runtime_config(market: str, output: str | None) -> RuntimeConfig:
    spec = MARKET_SPECS[market]
    return RuntimeConfig(
        spec=spec,
        max_symbols=_int_env("MARKET_FUNNEL_MAX_SYMBOLS", spec.default_max_symbols, minimum=1),
        kline_count=_int_env("MARKET_FUNNEL_KLINE_COUNT", 320, minimum=220),
        kline_batch_size=_int_env("MARKET_FUNNEL_KLINE_BATCH_SIZE", 80, minimum=1),
        kline_batch_sleep=_float_env("MARKET_FUNNEL_KLINE_BATCH_SLEEP", 0.4),
        min_quote_amount=_float_env("MARKET_FUNNEL_MIN_QUOTE_AMOUNT", spec.default_min_quote_amount),
        min_avg_amount=_float_env("MARKET_FUNNEL_MIN_AVG_AMOUNT", 0.0),
        min_history_rows=_int_env("MARKET_FUNNEL_MIN_HISTORY_ROWS", 220, minimum=80),
        output_path=Path(output) if output else None,
    )


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


def _rank_quotes(
    quotes: dict[str, dict[str, Any]],
    *,
    max_symbols: int,
    min_quote_amount: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, row in quotes.items():
        last_price = _row_float(row, "last_price", "close")
        if last_price is None or last_price <= 0:
            continue
        amount = _row_float(row, "amount") or 0.0
        if amount < min_quote_amount:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": _quote_name(row, symbol),
                "last_price": float(last_price),
                "amount": float(amount),
                "volume": float(_row_float(row, "volume") or 0.0),
                "change_pct": float(_quote_change_pct(row)),
            }
        )
    rows.sort(key=lambda item: (item["amount"], abs(item["change_pct"]), item["volume"]), reverse=True)
    return rows[:max_symbols]


def _chunks(items: list[str], size: int) -> list[list[str]]:
    width = max(int(size), 1)
    return [items[i : i + width] for i in range(0, len(items), width)]


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


def _funnel_config(cfg: RuntimeConfig) -> FunnelConfig:
    funnel_cfg = FunnelConfig(trading_days=cfg.kline_count)
    funnel_cfg.require_cn_main_or_chinext = False
    funnel_cfg.min_market_cap_yi = 0.0
    funnel_cfg.min_avg_amount_wan = cfg.min_avg_amount / 10000.0
    funnel_cfg.enable_rs_filter = False
    funnel_cfg.enable_rs_divergence_channel = False
    funnel_cfg.require_bench_latest_alignment = False
    return funnel_cfg


def _run_layers(
    symbols: list[str],
    name_map: dict[str, str],
    df_map: dict[str, pd.DataFrame],
    cfg: RuntimeConfig,
) -> tuple[dict[str, list[tuple[str, float]]], dict[str, Any]]:
    funnel_cfg = _funnel_config(cfg)
    layer1 = layer1_filter(symbols, name_map, {}, df_map, funnel_cfg)
    layer2, channel_map = layer2_strength_detailed(layer1, df_map, None, funnel_cfg, rps_universe=symbols)
    layer3, top_sectors = layer3_sector_resonance(layer2, {}, funnel_cfg, base_symbols=layer1, df_map=df_map)
    triggers = layer4_triggers(layer3, df_map, funnel_cfg)
    metrics = {
        "layer1": len(layer1),
        "layer2": len(layer2),
        "layer3": len(layer3),
        "total_hits": sum(len(items) for items in triggers.values()),
        "by_trigger": {key: len(items) for key, items in triggers.items()},
        "top_sectors": top_sectors,
        "layer2_channel_map": channel_map,
    }
    return triggers, metrics


def _latest_close(df: pd.DataFrame | None) -> float | None:
    if df is None or df.empty or "close" not in df.columns:
        return None
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    return float(close.iloc[-1]) if not close.empty else None


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
        item["latest_close"] = _latest_close(df_map.get(str(item["symbol"])))
    out.sort(key=lambda item: float(item["score"]), reverse=True)
    return out


def _write_output(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[market-funnel] result written: {path}")


def run_market_funnel(
    market: str,
    *,
    output: str | None = None,
    client: TickFlowClient | None = None,
) -> dict[str, Any]:
    runtime = _runtime_config(market, output)
    tf = client or TickFlowClient(api_key=os.getenv("TICKFLOW_API_KEY", "").strip())
    print(
        f"[market-funnel] start market={runtime.spec.key} universe={runtime.spec.universe} "
        f"max_symbols={runtime.max_symbols} kline_batch={runtime.kline_batch_size}"
    )
    quotes = tf.get_quotes(universes=[runtime.spec.universe])
    ranked = _rank_quotes(quotes, max_symbols=runtime.max_symbols, min_quote_amount=runtime.min_quote_amount)
    if not ranked and runtime.min_quote_amount > 0:
        print("[market-funnel] quote amount filter returned empty; retry ranking without amount floor")
        ranked = _rank_quotes(quotes, max_symbols=runtime.max_symbols, min_quote_amount=0.0)
    symbols = [str(item["symbol"]) for item in ranked]
    df_map, fetch_stats = _fetch_daily_histories(tf, symbols, runtime)
    fetched_symbols = [symbol for symbol in symbols if symbol in df_map]
    name_map = {str(item["symbol"]): str(item["name"]) for item in ranked}
    triggers, metrics = _run_layers(fetched_symbols, name_map, df_map, runtime) if df_map else ({}, {})
    result = {
        "ok": bool(quotes and df_map),
        "market": runtime.spec.key,
        "label": runtime.spec.label,
        "universe": runtime.spec.universe,
        "quote_count": len(quotes),
        "selected_count": len(symbols),
        "fetched_count": len(df_map),
        "fetch_stats": fetch_stats,
        "metrics": metrics,
        "top_candidates": _candidate_rows(triggers, name_map=name_map, df_map=df_map)[:50],
        "limits": {
            "max_symbols": runtime.max_symbols,
            "kline_batch_size": runtime.kline_batch_size,
            "kline_batch_sleep": runtime.kline_batch_sleep,
            "min_quote_amount": runtime.min_quote_amount,
        },
    }
    _write_output(runtime.output_path, result)
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
