"""Fixed-horizon event labels for recommendation tracking."""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime
from typing import Any


def build_horizon_event(
    row: dict[str, Any],
    ohlc: dict[str, dict[str, float]],
    *,
    horizon_days: int = 5,
    target_pct: float = 10.0,
) -> dict[str, Any]:
    horizon = max(int(horizon_days), 1)
    target = float(target_pct)
    trade_dates = sorted(ohlc)
    recommend_date = recommend_date_to_yyyymmdd(row.get("recommend_date"))
    entry_date = pick_close_on_or_before(trade_dates, recommend_date)
    entry_price = _entry_price(row, ohlc.get(entry_date))
    base = _base_event(row, recommend_date, entry_date, entry_price, horizon, target)
    if not entry_date or entry_price <= 0:
        return {**base, "label_ready": False, "label_status": "missing_entry"}

    window = _future_window(trade_dates, entry_date, horizon, ohlc)
    if not window:
        return {**base, "label_ready": False, "label_status": "missing_future_window"}
    return {**base, **_window_metrics(window, entry_price, horizon, target)}


def summarize_horizon_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [event for event in events if event.get("label_ready")]
    hits = [event for event in ready if event.get("hit_target")]
    drawdowns = [safe_float(event.get("mae_horizon_pct")) for event in ready]
    mfes = [safe_float(event.get("mfe_horizon_pct")) for event in ready]
    close_returns = _present_numbers(ready, "close_return_horizon_pct")
    winners = [value for value in close_returns if value > 0]
    losers = [value for value in close_returns if value < 0]
    avg_win = _avg(winners)
    avg_loss = _avg(losers)
    return {
        "rows_total": len(events),
        "rows_ready": len(ready),
        "rows_unready": len(events) - len(ready),
        "hit_count": len(hits),
        "hit_rate_pct": _pct(len(hits), len(ready)),
        "close_win_count": len(winners),
        "close_win_rate_pct": _pct(len(winners), len(close_returns)),
        "avg_close_return_horizon_pct": _avg(close_returns),
        "avg_winning_close_return_pct": avg_win,
        "avg_losing_close_return_pct": avg_loss,
        "close_payoff_ratio": _ratio(avg_win, abs(avg_loss) if avg_loss is not None else None),
        "avg_mfe_horizon_pct": _avg(mfes),
        "avg_mae_horizon_pct": _avg(drawdowns),
        "mfe_mae_ratio": _ratio(_avg(mfes), abs(_avg(drawdowns)) if drawdowns else None),
        "mae_le_neg5_count": sum(value <= -5.0 for value in drawdowns),
        "mae_le_neg5_rate_pct": _pct(sum(value <= -5.0 for value in drawdowns), len(drawdowns)),
    }


def _base_event(
    row: dict[str, Any],
    recommend_date: str,
    entry_date: str,
    entry_price: float,
    horizon: int,
    target: float,
) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "code": row.get("code"),
        "name": row.get("name"),
        "recommend_date": int(recommend_date) if recommend_date.isdigit() else None,
        "entry_date": int(entry_date) if entry_date.isdigit() else None,
        "entry_price": round(entry_price, 4) if entry_price > 0 else 0.0,
        "horizon_days": horizon,
        "target_pct": target,
        "is_ai_recommended": bool(row.get("is_ai_recommended")),
        "funnel_score": _safe_optional_float(row.get("funnel_score")),
        "recommend_count": _safe_optional_int(row.get("recommend_count")),
    }


def _entry_price(row: dict[str, Any], entry_row: dict[str, float] | None) -> float:
    row_price = safe_float(row.get("initial_price"), 0.0)
    if row_price > 0:
        return row_price
    return safe_float((entry_row or {}).get("close"), 0.0)


def _future_window(
    trade_dates: list[str],
    entry_date: str,
    horizon: int,
    ohlc: dict[str, dict[str, float]],
) -> list[tuple[str, dict[str, float]]]:
    return [(day, ohlc[day]) for day in trade_dates if day > entry_date][:horizon]


def _window_metrics(
    window: list[tuple[str, dict[str, float]]],
    entry_price: float,
    horizon: int,
    target: float,
) -> dict[str, Any]:
    high_date, high_row = max(window, key=lambda item: item[1]["high"])
    low_date, low_row = min(window, key=lambda item: item[1]["low"])
    close_date, close_row = window[-1]
    mfe = (float(high_row["high"]) / entry_price - 1.0) * 100.0
    mae = (float(low_row["low"]) / entry_price - 1.0) * 100.0
    close_ret = (float(close_row["close"]) / entry_price - 1.0) * 100.0
    first_hit = _first_hit_date(window, entry_price, target)
    return {
        "label_ready": len(window) >= horizon,
        "label_status": "ready" if len(window) >= horizon else "partial_window",
        "observed_days": len(window),
        "mfe_horizon_pct": round(mfe, 2),
        "mae_horizon_pct": round(mae, 2),
        "close_return_horizon_pct": round(close_ret, 2),
        "mfe_horizon_date": int(high_date),
        "mae_horizon_date": int(low_date),
        "window_end_date": int(close_date),
        "hit_target": mfe >= target,
        "first_hit_date": int(first_hit) if first_hit else None,
        "days_to_hit": _days_to_hit(window, first_hit),
    }


def _first_hit_date(window: list[tuple[str, dict[str, float]]], entry_price: float, target: float) -> str:
    for day, row in window:
        if (float(row["high"]) / entry_price - 1.0) * 100.0 >= target:
            return day
    return ""


def _days_to_hit(window: list[tuple[str, dict[str, float]]], first_hit: str) -> int | None:
    if not first_hit:
        return None
    for idx, (day, _) in enumerate(window, start=1):
        if day == first_hit:
            return idx
    return None


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _present_numbers(events: list[dict[str, Any]], key: str) -> list[float]:
    return [safe_float(event.get(key)) for event in events if event.get(key) is not None]


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 2) if denominator else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 2)


def _safe_optional_float(raw: Any) -> float | None:
    value = safe_float(raw, 0.0)
    return value if raw is not None else None


def _safe_optional_int(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def recommend_date_to_yyyymmdd(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if len(text) == 8 and text.isdigit():
        return text
    try:
        return datetime.fromisoformat(text).strftime("%Y%m%d")
    except ValueError:
        return ""


def pick_close_on_or_before(sorted_trade_dates: list[str], target_yyyymmdd: str) -> str:
    if not sorted_trade_dates or not target_yyyymmdd:
        return ""
    index = bisect_right(sorted_trade_dates, target_yyyymmdd) - 1
    return "" if index < 0 else sorted_trade_dates[index]
