"""Intraday market repair overlay for tail-buy scans."""

from __future__ import annotations

from typing import Any

from core.tail_buy.models import TailBuyCandidate, safe_float
from core.tail_buy.strategy import compute_tail_features
from integrations.tickflow_client import TickFlowClient
from workflows.tail_buy_utils import log_line

INTRADAY_REPAIR_MODE = "PANIC_REPAIR_INTRADAY"
INTRADAY_CRASH_MODE = "CRASH_INTRADAY"
_INDEX_SYMBOLS = ("000001.SH", "399006.SZ")
_WEAK_REGIME_TOKENS = ("CRASH", "RISK_OFF", "PANIC_REPAIR", "BEAR_REBOUND", "BLACK_SWAN")


_REGIME_PRIORITY = {
    "BLACK_SWAN": 0,
    "CRASH": 1,
    "CRASH_INTRADAY": 2,
    "RISK_OFF": 3,
    "PANIC_REPAIR_CONFIRMED": 4,
    "PANIC_REPAIR_INTRADAY": 5,
    "PANIC_REPAIR": 6,
    "BEAR_REBOUND": 7,
    "CRASH_LEFT_PROBE": 8,
    "RISK_ON": 9,
    "NEUTRAL": 10,
    "CAUTION": 11,
    "NORMAL": 12,
    "UNKNOWN": 13,
}


def more_defensive_regime(a: str, b: str) -> str:
    pa = _REGIME_PRIORITY.get(str(a or "").strip().upper(), 99)
    pb = _REGIME_PRIORITY.get(str(b or "").strip().upper(), 99)
    return a if pa <= pb else b


def apply_base_market_regime(
    candidates: list[TailBuyCandidate],
    *,
    benchmark: str = "",
    premarket: str = "",
) -> int:
    regime = (
        more_defensive_regime(benchmark, premarket)
        if benchmark and premarket
        else (benchmark or premarket or "UNKNOWN")
    )
    changed = 0
    for item in candidates:
        if str(item.market_regime or "").strip().upper() != regime:
            item.market_regime = regime
            changed += 1
    return changed


def resolve_intraday_market_mode(
    tickflow_client: TickFlowClient,
    *,
    market_reminder: str,
    logs_path: str | None = None,
) -> tuple[str, str]:
    if not _previous_market_was_weak(market_reminder):
        return "", "昨晚市场水温非防守态，不启用盘中修复覆盖"
    try:
        data_map = tickflow_client.get_intraday_batch(list(_INDEX_SYMBOLS), period="1m", count=5000)
    except Exception as exc:
        log_line(f"盘中市场修复识别失败: {exc}", logs_path)
        return "", f"盘中市场修复识别失败: {exc}"
    metrics = _index_metrics(data_map)
    mode, reason = _classify_intraday_market(metrics)
    if mode:
        log_line(f"盘中市场模式覆盖: {mode} | {reason}", logs_path)
    return mode, reason


def apply_intraday_market_mode(
    candidates: list[TailBuyCandidate],
    *,
    mode: str,
    logs_path: str | None = None,
) -> int:
    mode_norm = str(mode or "").strip().upper()
    if not mode_norm:
        return 0
    changed = 0
    for item in candidates:
        old = str(item.market_regime or "").strip().upper()
        if mode_norm == INTRADAY_CRASH_MODE or old in _WEAK_REGIME_TOKENS:
            item.market_regime = mode_norm
            changed += 1
    if changed:
        log_line(f"尾盘候选市场标签覆盖: mode={mode_norm}, affected={changed}", logs_path)
    return changed


def append_intraday_market_reminder(market_reminder: str, mode: str, reason: str) -> str:
    if not mode:
        return market_reminder
    suffix = f"盘中覆盖={mode} | {reason}"
    return f"{market_reminder} | {suffix}" if market_reminder else suffix


def _previous_market_was_weak(market_reminder: str) -> bool:
    text = str(market_reminder or "").upper()
    return "UNKNOWN" in text or any(token in text for token in _WEAK_REGIME_TOKENS)


def _index_metrics(data_map: dict[str, Any]) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for symbol in _INDEX_SYMBOLS:
        frame = data_map.get(symbol)
        if frame is None:
            frame = data_map.get(symbol.replace(".SH", "").replace(".SZ", ""))
        features = compute_tail_features(frame)
        metrics[symbol] = {
            "day_ret_pct": safe_float(features.get("day_ret_pct"), 0.0),
            "close_pos": safe_float(features.get("close_pos"), 0.0),
            "last30_ret_pct": safe_float(features.get("last30_ret_pct"), 0.0),
            "dist_vwap_pct": safe_float(features.get("dist_vwap_pct"), 0.0),
            "drop_from_high_pct": safe_float(features.get("drop_from_high_pct"), 0.0),
        }
    return metrics


def _classify_intraday_market(metrics: dict[str, dict[str, float]]) -> tuple[str, str]:
    main = metrics.get("000001.SH") or {}
    small = metrics.get("399006.SZ") or {}
    if _intraday_crash(main, small):
        return INTRADAY_CRASH_MODE, _reason("盘中继续杀跌", main, small)
    if _intraday_repair(main, small):
        return INTRADAY_REPAIR_MODE, _reason("盘中修复成立", main, small)
    return "", _reason("盘中修复不足", main, small)


def _intraday_repair(main: dict[str, float], small: dict[str, float]) -> bool:
    price_ok = main.get("day_ret_pct", 0.0) >= 0.6 or small.get("day_ret_pct", 0.0) >= 1.2
    tail_ok = main.get("close_pos", 0.0) >= 0.62 and small.get("close_pos", 0.0) >= 0.58
    vwap_ok = main.get("dist_vwap_pct", 0.0) >= -0.15 or small.get("dist_vwap_pct", 0.0) >= -0.15
    return bool(price_ok and tail_ok and vwap_ok)


def _intraday_crash(main: dict[str, float], small: dict[str, float]) -> bool:
    price_bad = main.get("day_ret_pct", 0.0) <= -1.2 or small.get("day_ret_pct", 0.0) <= -2.2
    tail_bad = main.get("close_pos", 1.0) < 0.35 and small.get("close_pos", 1.0) < 0.35
    return bool(price_bad and tail_bad)


def _reason(prefix: str, main: dict[str, float], small: dict[str, float]) -> str:
    return (
        f"{prefix}: 上证{main.get('day_ret_pct', 0.0):+.2f}%/pos{main.get('close_pos', 0.0):.2f}, "
        f"创业板{small.get('day_ret_pct', 0.0):+.2f}%/pos{small.get('close_pos', 0.0):.2f}"
    )
