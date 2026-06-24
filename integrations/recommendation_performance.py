"""Post-entry performance refresh for global recommendation tracking tables."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from core.constants import TABLE_RECOMMENDATION_TRACKING_US
from integrations.recommendation_tracking_common import (
    fetch_records_from_table,
    ohlc_map_from_tickflow_hist,
    pick_close_on_or_before,
    recommend_date_to_yyyymmdd,
    safe_float,
    upsert_to_table,
)
from integrations.supabase_base import create_admin_client, is_admin_configured, require_server_write_context


def refresh_us_tracking_performance(max_dates: int = 60, kline_count: int = 160) -> dict[str, Any]:
    if not is_admin_configured():
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 未配置")
    require_server_write_context("refresh US tracking performance")
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TICKFLOW_API_KEY 未配置")

    client = create_admin_client()
    records = fetch_records_from_table(client, TABLE_RECOMMENDATION_TRACKING_US, "id,code,recommend_date,initial_price")
    records = latest_market_records(records, max_dates)
    if not records:
        return empty_us_performance_summary()

    grouped = _group_records_by_code(records)
    hist_map = _fetch_us_histories(api_key, sorted(grouped), kline_count)
    now_iso = datetime.now(UTC).isoformat()
    updates, codes_no_data, latest_td = build_us_performance_updates(grouped, hist_map, now_iso)
    written = upsert_to_table(client, TABLE_RECOMMENDATION_TRACKING_US, updates)
    return us_performance_summary(records, grouped, written, codes_no_data, latest_td, updates)


def latest_market_records(records: list[dict[str, Any]], max_dates: int) -> list[dict[str, Any]]:
    limit = max(int(max_dates), 1)
    dates = sorted(
        {day for day in (recommend_date_to_yyyymmdd(row.get("recommend_date")) for row in records) if day},
        reverse=True,
    )[:limit]
    allowed = set(dates)
    return [row for row in records if recommend_date_to_yyyymmdd(row.get("recommend_date")) in allowed]


def build_us_performance_updates(
    grouped: dict[str, list[dict[str, Any]]],
    hist_map: dict[str, pd.DataFrame],
    now_iso: str,
) -> tuple[list[dict[str, Any]], int, str]:
    updates: list[dict[str, Any]] = []
    codes_no_data = 0
    latest_td = ""
    for code, rows in grouped.items():
        ohlc = ohlc_map_from_tickflow_hist(hist_map.get(code))
        trade_dates = sorted(ohlc)
        if not trade_dates:
            codes_no_data += 1
            continue
        latest_td = max(latest_td, trade_dates[-1])
        updates.extend(row for row in (_build_us_performance_update(row, code, ohlc, now_iso) for row in rows) if row)
    return updates, codes_no_data, latest_td


def empty_us_performance_summary() -> dict[str, Any]:
    return {
        "rows_total": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
        "codes_total": 0,
        "codes_no_data": 0,
        "latest_trade_date": "",
        "mfe_ge_5": 0,
        "mfe_ge_10": 0,
        "mae_le_neg5": 0,
    }


def us_performance_summary(
    records: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    written: int,
    codes_no_data: int,
    latest_trade_date: str,
    updates: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = empty_us_performance_summary()
    summary.update(
        {
            "rows_total": len(records),
            "rows_updated": written,
            "rows_skipped": max(len(records) - written, 0),
            "codes_total": len(grouped),
            "codes_no_data": codes_no_data,
            "latest_trade_date": latest_trade_date,
            "mfe_ge_5": sum(safe_float(row.get("mfe_pct")) >= 5.0 for row in updates),
            "mfe_ge_10": sum(safe_float(row.get("mfe_pct")) >= 10.0 for row in updates),
            "mae_le_neg5": sum(safe_float(row.get("mae_pct")) <= -5.0 for row in updates),
        }
    )
    return summary


def _build_us_performance_update(
    row: dict[str, Any],
    code: str,
    ohlc: dict[str, dict[str, float]],
    now_iso: str,
) -> dict[str, Any] | None:
    trade_dates = sorted(ohlc)
    recommend_date = recommend_date_to_yyyymmdd(row.get("recommend_date"))
    entry_date = pick_close_on_or_before(trade_dates, recommend_date)
    if not entry_date:
        return None
    entry = safe_float(ohlc.get(entry_date, {}).get("close"), 0.0)
    if entry <= 0:
        entry = safe_float(row.get("initial_price"), 0.0)
    return _performance_row(
        row, code, recommend_date, entry, [(day, ohlc[day]) for day in trade_dates if day >= entry_date], now_iso
    )


def _performance_row(
    row: dict[str, Any],
    code: str,
    recommend_date: str,
    entry: float,
    window: list[tuple[str, dict[str, float]]],
    now_iso: str,
) -> dict[str, Any] | None:
    if entry <= 0 or not window:
        return None
    high_date, high_row = max(window, key=lambda item: item[1]["high"])
    low_date, low_row = min(window, key=lambda item: item[1]["low"])
    latest_date, latest_row = window[-1]
    mfe_price = float(high_row["high"])
    mae_price = float(low_row["low"])
    current_price = float(latest_row["close"])
    return {
        "id": row.get("id"),
        "code": code,
        "recommend_date": int(recommend_date) if recommend_date.isdigit() else None,
        "initial_price": round(entry, 4),
        "current_price": round(current_price, 4),
        "change_pct": round((current_price / entry - 1.0) * 100.0, 2),
        "mfe_pct": round((mfe_price / entry - 1.0) * 100.0, 2),
        "mae_pct": round((mae_price / entry - 1.0) * 100.0, 2),
        "range_amp_pct": round((mfe_price / mae_price - 1.0) * 100.0, 2) if mae_price > 0 else 0.0,
        "mfe_price": round(mfe_price, 4),
        "mae_price": round(mae_price, 4),
        "mfe_date": int(high_date),
        "mae_date": int(low_date),
        "performance_days": len(window),
        "performance_updated_at": now_iso,
        "updated_at": now_iso,
    }


def _group_records_by_code(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        code = str(row.get("code") or "").strip()
        if code:
            grouped.setdefault(code, []).append(row)
    return grouped


def _fetch_us_histories(api_key: str, symbols: list[str], kline_count: int) -> dict[str, pd.DataFrame]:
    from integrations.tickflow_client import TickFlowClient

    client = TickFlowClient(api_key=api_key)
    return client.get_klines_batch(symbols, period="1d", count=max(int(kline_count), 1), adjust="forward")
