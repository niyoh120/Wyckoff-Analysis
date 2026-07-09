"""HK funnel risk gate: drop penny-stock / illiquid / splitlike symbols before scoring."""

from __future__ import annotations

import pandas as pd

from core.hk_risk_filter import classify_hk_risk, describe_hk_risk
from core.wyckoff_engine import dollar_volume_series

AVG_TURNOVER_LOOKBACK_DAYS = 20


def apply_hk_risk_gate(
    symbols: list[str],
    df_map: dict[str, pd.DataFrame],
    *,
    logs_path: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """返回通过港股风险门禁的标的列表，以及被剔除标的的原因映射（供报告展示）。"""
    kept: list[str] = []
    blocked: dict[str, str] = {}
    for symbol in symbols:
        reason = _hk_block_reason(df_map.get(symbol))
        if reason:
            blocked[symbol] = reason
        else:
            kept.append(symbol)
    if blocked:
        _log(f"[hk-risk-gate] blocked={len(blocked)}/{len(symbols)} symbols={list(blocked)[:10]}", logs_path)
    return kept, blocked


def _hk_block_reason(df: pd.DataFrame | None) -> str:
    if df is None or df.empty or "close" not in df.columns:
        return ""
    work = df.dropna(subset=["close"]).sort_values("date") if "date" in df.columns else df.dropna(subset=["close"])
    if work.empty:
        return ""
    latest = work.iloc[-1]
    prev_close = float(work.iloc[-2]["close"]) if len(work) >= 2 else 0.0
    avg_turnover = _avg_turnover(work)
    flags = classify_hk_risk(
        close=float(latest.get("close") or 0.0),
        open_=float(latest.get("open") or 0.0),
        prev_close=prev_close,
        pct_chg=float(latest.get("pct_chg") or 0.0),
        avg_turnover_hkd=avg_turnover,
    )
    return describe_hk_risk(flags) if flags.blocked else ""


def _avg_turnover(work: pd.DataFrame) -> float:
    """计算近期日均成交额；TickFlow 港股 amount 字段恒为 0 时由 dollar_volume_series 回退为 close*volume。"""
    tail = dollar_volume_series(work).tail(AVG_TURNOVER_LOOKBACK_DAYS)
    return float(tail.mean()) if not tail.empty else float("inf")


def _log(message: str, logs_path: str | None) -> None:
    print(message)
    if not logs_path:
        return
    try:
        with open(logs_path, "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        pass


__all__ = ["apply_hk_risk_gate"]
