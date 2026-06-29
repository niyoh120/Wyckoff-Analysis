"""Agent-facing stock price and Wyckoff diagnosis tools."""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

from agents.stock_data_helpers import (
    code_to_name,
    collect_tickflow_limit_hints_from_df,
    hist_metadata,
    latest_hist_date,
)
from agents.tool_context import ToolContext, ensure_tushare_token

logger = logging.getLogger(__name__)


def analyze_stock(
    code: str, mode: str = "diagnose", cost: float = 0.0, days: int = 30, tool_context: ToolContext | None = None
) -> dict:
    """分析单只 A 股股票：Wyckoff 健康诊断或近期行情查询。"""
    try:
        ensure_tushare_token(tool_context)
        mode = (mode or "diagnose").strip().lower()
        if mode not in ("diagnose", "price"):
            return {"error": f"mode 参数无效: '{mode}'，可选值: diagnose, price"}
        end_date = date.today()
        if mode == "price":
            return _price_result(code, days, end_date)
        return _diagnosis_result(code, cost, end_date)
    except Exception as e:
        logger.exception("analyze_stock error")
        return {"error": str(e)}


def _price_result(code: str, days: int, end_date: date) -> dict:
    from integrations.stock_hist_repository import get_stock_hist, normalize_hist_df

    days = min(max(days, 1), 250)
    start_date = end_date - timedelta(days=int(days * 1.6))
    df = get_stock_hist(code, start_date, end_date)
    if df is None or df.empty:
        return {"error": f"无法获取 {code} 的行情数据"}
    hist_hints = collect_tickflow_limit_hints_from_df(df)
    hist_meta = hist_metadata(df)
    df = normalize_hist_df(df).tail(days)
    latest = df.iloc[-1] if len(df) > 0 else {}
    payload = {
        "code": code,
        "days": len(df),
        "latest_close": _round_number(latest.get("close")),
        "latest_date": str(latest.get("date", "")),
        "data_status": "ok",
        **hist_meta,
        "data": _price_records(df),
    }
    if hist_hints:
        payload["tickflow_limit_hint"] = hist_hints[0]
    return payload


def _price_records(df) -> list[dict]:
    return [
        {
            "date": str(row.get("date", "")),
            "open": _round_number(row.get("open")),
            "high": _round_number(row.get("high")),
            "low": _round_number(row.get("low")),
            "close": _round_number(row.get("close")),
            "volume": _safe_int(row.get("volume")),
            "pct_chg": _round_number(row.get("pct_chg")),
        }
        for _, row in df.iterrows()
    ]


def _diagnosis_result(code: str, cost: float, end_date: date) -> dict:
    from core.holding_diagnostic import diagnose_one_stock, format_diagnostic_text
    from integrations.stock_hist_repository import get_stock_hist, normalize_hist_df

    df = get_stock_hist(code, end_date - timedelta(days=500), end_date)
    if df is None or df.empty:
        return {"error": f"无法获取 {code} 的行情数据"}
    hist_hints = collect_tickflow_limit_hints_from_df(df)
    hist_meta = hist_metadata(df)
    latest_date = latest_hist_date(df, "日期")
    df = normalize_hist_df(df)
    diagnostic = diagnose_one_stock(code, code_to_name(code), cost, df)
    payload = _diagnostic_payload(
        diagnostic,
        format_diagnostic_text(diagnostic),
        latest_date or latest_hist_date(df),
        hist_meta,
    )
    if hist_hints:
        payload["tickflow_limit_hint"] = hist_hints[0]
    return payload


def _diagnostic_payload(d, text: str, latest_date: str, metadata: dict) -> dict:
    return {
        "code": d.code,
        "name": d.name,
        "health": d.health,
        "pnl_pct": _round_number(d.pnl_pct),
        "latest_close": _round_number(d.latest_close),
        "ma_pattern": d.ma_pattern,
        "l2_channel": d.l2_channel,
        "track": d.track,
        "accum_stage": d.accum_stage,
        "l4_triggers": d.l4_triggers,
        "candidate_lane": d.candidate_lane,
        "candidate_entry_type": d.candidate_entry_type,
        "candidate_score": _round_number(d.candidate_score),
        "exit_signal": d.exit_signal,
        "stop_loss_status": d.stop_loss_status,
        "vol_ratio_20_60": _round_number(d.vol_ratio_20_60),
        "range_60d_pct": _round_number(d.range_60d_pct, 1),
        "ret_10d_pct": _round_number(d.ret_10d_pct, 1),
        "ret_20d_pct": _round_number(d.ret_20d_pct, 1),
        "from_year_high_pct": _round_number(d.from_year_high_pct, 1),
        "from_year_low_pct": _round_number(d.from_year_low_pct, 1),
        "health_reasons": d.health_reasons,
        "formatted_text": text,
        "data_status": "ok",
        "latest_date": latest_date,
        **metadata,
    }


def _round_number(value: Any, digits: int = 2) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return round(out, digits) if math.isfinite(out) else None


def _safe_int(value: Any) -> int:
    rounded = _round_number(value, 0)
    return int(rounded) if rounded is not None else 0
