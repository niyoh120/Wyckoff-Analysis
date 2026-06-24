"""Realtime spot snapshot patching for missing latest daily bars."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from core.hist_dates import latest_trade_date_from_hist
from integrations.spot_snapshot import fetch_stock_spot_snapshot
from utils.trading_clock import CN_TZ

_TRUE_TEXTS = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SpotPatchBasis:
    frame: pd.DataFrame
    prev_close: float | None
    prev_volume: float | None
    prev_amount: float | None


def _env_enabled(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUE_TEXTS


def _spot_patch_allowed(df: pd.DataFrame, target_trade_date: date, env_prefix: str) -> bool:
    if not _env_enabled(f"{env_prefix}_ENABLE_SPOT_PATCH"):
        return False
    if df is None or df.empty:
        return False
    latest_trade = latest_trade_date_from_hist(df)
    if latest_trade is None or latest_trade >= target_trade_date:
        return False
    return target_trade_date == datetime.now(CN_TZ).date()


def _latest_numeric(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    series = pd.to_numeric(frame.get(column), errors="coerce").dropna()
    return float(series.iloc[-1]) if not series.empty else None


def _spot_patch_basis(df: pd.DataFrame, zero_fallback: bool) -> SpotPatchBasis:
    frame = df.sort_values("date").reset_index(drop=True)
    return SpotPatchBasis(
        frame=frame,
        prev_close=_latest_numeric(frame, "close"),
        prev_volume=None if zero_fallback else _latest_numeric(frame, "volume"),
        prev_amount=None if zero_fallback else _latest_numeric(frame, "amount"),
    )


def _spot_turnover_values(
    snap: dict,
    basis: SpotPatchBasis,
    zero_fallback: bool,
) -> tuple[float, float]:
    turnover_ok = bool(float(snap.get("turnover_unit_ok", 0.0)))
    if turnover_ok:
        volume = float(snap.get("volume")) if snap.get("volume") is not None else 0.0
        amount = float(snap.get("amount")) if snap.get("amount") is not None else 0.0
        return volume, amount
    if zero_fallback:
        return 0.0, 0.0
    volume = float(basis.prev_volume) if basis.prev_volume is not None else float("nan")
    amount = float(basis.prev_amount) if basis.prev_amount is not None else float("nan")
    return volume, amount


def _spot_patch_row(
    snap: dict,
    basis: SpotPatchBasis,
    target_trade_date: date,
    zero_fallback: bool,
) -> dict[str, float | str]:
    close_f = float(snap.get("close"))
    open_f = float(snap.get("open")) if snap.get("open") is not None else close_f
    high_raw = float(snap.get("high")) if snap.get("high") is not None else close_f
    low_raw = float(snap.get("low")) if snap.get("low") is not None else close_f
    volume_f, amount_f = _spot_turnover_values(snap, basis, zero_fallback)
    pct_f = float(snap.get("pct_chg")) if snap.get("pct_chg") is not None else None
    if pct_f is None and basis.prev_close and basis.prev_close > 0:
        pct_f = (close_f - basis.prev_close) / basis.prev_close * 100.0
    return {
        "date": target_trade_date.isoformat(),
        "open": open_f,
        "high": max(high_raw, open_f, close_f),
        "low": min(low_raw, open_f, close_f),
        "close": close_f,
        "volume": volume_f,
        "amount": amount_f,
        "pct_chg": pct_f if pct_f is not None else 0.0,
    }


def append_spot_bar_if_needed(
    code: str,
    df: pd.DataFrame,
    target_trade_date: date,
    *,
    env_prefix: str = "FUNNEL",
    sleep_default: float = 0.2,
    zero_fallback: bool = False,
) -> tuple[pd.DataFrame, bool]:
    """
    如果 DataFrame 最新交易日缺失且今天是目标交易日，
    通过实时行情补丁补齐最后一根 bar。

    Parameters
    ----------
    code : str
        股票代码
    env_prefix : str
        环境变量前缀，用于读取 {prefix}_ENABLE_SPOT_PATCH 等配置。
        默认 "FUNNEL"，step3 传 "STEP3"，step4 传 "STEP4"。
    sleep_default : float
        重试间隔默认值（秒）。
    zero_fallback : bool
        turnover_ok=False 时的回退策略：
        True  → volume/amount 置 0（避免污染均量/ATR 计算，step3/step4 行为）
        False → 沿用前一日 volume/amount 或 NaN（funnel 行为）
    """
    if not _spot_patch_allowed(df, target_trade_date, env_prefix):
        return (df, False)

    retries = int(os.getenv(f"{env_prefix}_SPOT_PATCH_RETRIES", "2"))
    sleep_s = float(os.getenv(f"{env_prefix}_SPOT_PATCH_SLEEP", str(sleep_default)))
    basis = _spot_patch_basis(df, zero_fallback)

    for attempt in range(max(retries, 1)):
        snap = fetch_stock_spot_snapshot(code, force_refresh=attempt > 0)
        close_v = None if not snap else snap.get("close")
        if close_v is None or float(close_v) <= 0:
            if attempt < max(retries, 1) - 1:
                time.sleep(max(sleep_s, 0.0))
            continue

        patched = pd.concat(
            [basis.frame, pd.DataFrame([_spot_patch_row(snap, basis, target_trade_date, zero_fallback)])],
            ignore_index=True,
        )
        patched = patched.sort_values("date").reset_index(drop=True)
        return (patched, True)
    return (df, False)
