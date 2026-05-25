#!/usr/bin/env python3
"""Refresh signal outcomes and aggregate signal health."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

if __name__ == "__main__" or not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.signal_feedback import build_signal_registry_updates, summarize_signal_health
from core.signal_lifecycle import evaluate_signal_lifecycle
from integrations.supabase_signal_feedback import (
    load_recent_signal_observations,
    load_recent_signal_outcomes,
    load_signal_registry,
    upsert_signal_health,
    upsert_signal_outcomes,
    upsert_signal_registry,
)

_COLUMN_MAP = {"日期": "date", "收盘": "close", "最低": "low"}


def _parse_horizons(raw: str) -> tuple[int, ...]:
    values = []
    for item in str(raw or "").split(","):
        text = item.strip()
        if text:
            values.append(max(int(text), 1))
    return tuple(values or [1, 3, 5, 10, 20])


def _date_minus(raw: Any, days: int) -> str:
    parsed = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    return (parsed - timedelta(days=max(days, 0))).isoformat()


def _normalize_history(raw: pd.DataFrame | None) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    out = raw.rename(columns={k: v for k, v in _COLUMN_MAP.items() if k in raw.columns}).copy()
    keep = [c for c in ("date", "close", "low") if c in out.columns]
    if "date" not in keep or "close" not in keep:
        return pd.DataFrame()
    return out[keep]


def _fetch_history(obs: dict[str, Any], end_date: str, pre_days: int) -> pd.DataFrame:
    if str(obs.get("market") or "cn").lower() != "cn":
        return pd.DataFrame()
    from integrations.data_source import fetch_stock_hist

    start_date = _date_minus(obs.get("trade_date"), pre_days)
    raw = fetch_stock_hist(str(obs.get("code") or ""), start_date, end_date, adjust="qfq")
    return _normalize_history(raw)


def _outcome_rows(obs: dict[str, Any], hist: pd.DataFrame, horizons: tuple[int, ...]) -> list[dict[str, Any]]:
    if hist.empty or obs.get("id") is None:
        return []
    lifecycle = evaluate_signal_lifecycle(
        hist,
        code=str(obs.get("code") or ""),
        signal_date=str(obs.get("trade_date") or ""),
        entry_price=obs.get("entry_price"),
        horizons=horizons,
    )
    rows = []
    for outcome in lifecycle.outcomes:
        rows.append(
            {
                "observation_id": obs["id"],
                "market": obs.get("market") or "cn",
                "trade_date": obs.get("trade_date"),
                "code": str(obs.get("code") or ""),
                "signal_type": str(obs.get("signal_type") or ""),
                "track": str(obs.get("track") or ""),
                "regime": str(obs.get("regime") or "NEUTRAL"),
                "horizon_days": outcome.horizon,
                "status": outcome.status,
                "return_pct": outcome.return_pct,
                "max_drawdown_pct": outcome.max_drawdown_pct,
            }
        )
    return rows


def refresh_outcomes(args: argparse.Namespace) -> int:
    observations = load_recent_signal_observations(args.observation_days, args.limit, args.market)
    cache: dict[tuple[str, str, str], pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    for obs in observations:
        cache_key = (
            str(obs.get("market") or args.market),
            str(obs.get("code") or ""),
            str(obs.get("trade_date") or ""),
        )
        if cache_key not in cache:
            cache[cache_key] = _fetch_history(obs, args.end_date, args.pre_days)
        rows.extend(_outcome_rows(obs, cache[cache_key], args.horizons))
    written = upsert_signal_outcomes(rows)
    print(f"[signal_feedback] outcomes: observations={len(observations)}, rows={len(rows)}, written={written}")
    return written


def refresh_health(args: argparse.Namespace) -> int:
    outcomes = load_recent_signal_outcomes(args.outcome_days, args.outcome_limit, args.market)
    health_rows = summarize_signal_health(
        outcomes,
        as_of_date=args.as_of_date,
        market=args.market,
        min_samples=args.min_samples,
    )
    health_written = upsert_signal_health(health_rows)
    existing_registry = load_signal_registry(args.market)
    registry_rows = build_signal_registry_updates(
        health_rows,
        market=args.market,
        horizon_days=args.registry_horizon,
        registry_rows=existing_registry,
    )
    registry_written = upsert_signal_registry(registry_rows)
    print(f"[signal_feedback] health: outcomes={len(outcomes)}, health={health_written}, registry={registry_written}")
    return health_written


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh Wyckoff signal feedback tables.")
    parser.add_argument("--market", default="cn")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--horizons", type=_parse_horizons, default=_parse_horizons("1,3,5,10,20"))
    parser.add_argument("--observation-days", type=int, default=120)
    parser.add_argument("--outcome-days", type=int, default=180)
    parser.add_argument("--pre-days", type=int, default=10)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--outcome-limit", type=int, default=20000)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--registry-horizon", type=int, default=10)
    parser.add_argument("--health-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.health_only:
        refresh_outcomes(args)
    refresh_health(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
