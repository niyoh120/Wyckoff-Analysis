"""Daily-bar proxy replay for the CRASH left-probe execution chain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean

import pandas as pd

from core.candidate_policy import candidate_score_value
from core.signal_confirmation import build_snap, build_today_ohlcv, check_confirmation


@dataclass(frozen=True)
class CrashProbeObservation:
    code: str
    signal_date: date
    score: float
    snap: dict


@dataclass(frozen=True)
class _QualifiedProbe:
    observation: CrashProbeObservation
    probe_date: date
    probe_close: float


def build_crash_probe_observations(
    regime: str,
    signal_date: date,
    triggers: dict[str, list],
    day_df_map: dict[str, pd.DataFrame],
) -> list[CrashProbeObservation]:
    if str(regime).strip().upper() != "CRASH":
        return []
    return [
        item
        for code, score in triggers.get("crash_resilience_watch", [])
        if str(code) in day_df_map
        if (item := _observation(str(code), signal_date, candidate_score_value(score), day_df_map)) is not None
    ]


def summarize_crash_probe_replay(
    observations: list[CrashProbeObservation],
    all_df_map: dict[str, pd.DataFrame],
    trade_dates: list[date],
    *,
    hold_days: int,
    buy_friction_pct: float,
    sell_friction_pct: float,
) -> dict[str, float | int | str | None]:
    qualified = [
        item
        for observation in observations
        if (item := _qualified_probe(observation, all_df_map, trade_dates)) is not None
    ]
    selected = _top_probe_per_signal_day(qualified)
    outcomes = [
        outcome
        for item in selected
        if (outcome := _replay_outcome(item, all_df_map, trade_dates, hold_days, buy_friction_pct, sell_friction_pct))
        is not None
    ]
    confirmed = [item for item in outcomes if item["status"] == "confirmed"]
    return {
        "method": "t_plus_1_daily_close_proxy",
        "research_only": True,
        "same_close_entry_proxy": True,
        "signal_available_before_entry": True,
        "portfolio_accounted": False,
        "commission_included": False,
        "watch_candidates": len(observations),
        "proxy_qualified": len(qualified),
        "staged_entries": len(outcomes),
        "confirmed_next_day": len(confirmed),
        "failed_or_pending_next_day": len(outcomes) - len(confirmed),
        "confirmation_rate_pct": _pct(len(confirmed), len(outcomes)),
        "avg_probe_next_day_ret_pct": _avg(outcomes, "next_day_ret_pct"),
        "probe_2pct_capital_return_pct": sum(float(item["probe_pnl_pct"]) for item in outcomes),
        "confirmed_add_3pct_capital_return_pct": sum(float(item["add_pnl_pct"]) for item in outcomes),
        "staged_2_to_5pct_capital_return_pct": sum(float(item["staged_pnl_pct"]) for item in outcomes),
    }


def _observation(
    code: str,
    signal_date: date,
    score: float,
    day_df_map: dict[str, pd.DataFrame],
) -> CrashProbeObservation | None:
    df = day_df_map.get(code)
    if df is None or df.empty:
        return None
    snap = build_snap("crash_resilience_watch", df, score)
    return CrashProbeObservation(code, signal_date, score, snap)


def _qualified_probe(
    observation: CrashProbeObservation,
    all_df_map: dict[str, pd.DataFrame],
    trade_dates: list[date],
) -> _QualifiedProbe | None:
    try:
        probe_date = trade_dates[trade_dates.index(observation.signal_date) + 1]
    except (ValueError, IndexError):
        return None
    probe_slice = _slice_to(all_df_map.get(observation.code), probe_date)
    if probe_slice is None:
        return None
    last = probe_slice.iloc[-1]
    support = float(observation.snap.get("snap_support") or 0.0)
    low, high, close = (float(last[name]) for name in ("low", "high", "close"))
    close_pos = (close - low) / (high - low) if high > low else 0.5
    if support <= 0 or low >= support * 0.997 or close < support or close_pos < 0.65:
        return None
    return _QualifiedProbe(observation, probe_date, close)


def _top_probe_per_signal_day(qualified: list[_QualifiedProbe]) -> list[_QualifiedProbe]:
    winners: dict[date, _QualifiedProbe] = {}
    for item in qualified:
        observation = item.observation
        current = winners.get(observation.signal_date)
        if current is None:
            winners[observation.signal_date] = item
            continue
        incumbent = current.observation
        if (observation.score, observation.code) > (incumbent.score, incumbent.code):
            winners[observation.signal_date] = item
    return [winners[day] for day in sorted(winners)]


def _replay_outcome(
    probe: _QualifiedProbe,
    all_df_map: dict[str, pd.DataFrame],
    trade_dates: list[date],
    hold_days: int,
    buy_friction_pct: float,
    sell_friction_pct: float,
) -> dict[str, float | str] | None:
    observation = probe.observation
    try:
        signal_idx = trade_dates.index(observation.signal_date)
    except ValueError:
        return None
    confirmation_idx = signal_idx + 2
    if confirmation_idx >= len(trade_dates):
        return None
    df = all_df_map.get(observation.code)
    confirmation_slice = _slice_to(df, trade_dates[confirmation_idx])
    if confirmation_slice is None:
        return None
    entry = probe.probe_close
    today = build_today_ohlcv(confirmation_slice)
    status, _ = check_confirmation("crash_resilience_watch", observation.snap, today, 1)
    next_close = float(today["close"])
    exit_idx = min(confirmation_idx + max(hold_days, 1), len(trade_dates) - 1)
    exit_slice = _slice_to(df, trade_dates[exit_idx])
    exit_close = float(exit_slice.iloc[-1]["close"]) if status == "confirmed" and exit_slice is not None else next_close
    probe_ret = _net_return(entry, exit_close, buy_friction_pct, sell_friction_pct)
    add_ret = _net_return(next_close, exit_close, buy_friction_pct, sell_friction_pct) if status == "confirmed" else 0.0
    return {
        "status": status,
        "next_day_ret_pct": (next_close / entry - 1.0) * 100.0,
        "probe_pnl_pct": probe_ret * 2.0,
        "add_pnl_pct": add_ret * 3.0,
        "staged_pnl_pct": probe_ret * 2.0 + add_ret * 3.0,
    }


def _slice_to(df: pd.DataFrame | None, target: date) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    out = df[df["date"] <= target].sort_values("date")
    return None if out.empty or out.iloc[-1]["date"] != target else out


def _net_return(entry: float, exit_: float, buy_friction_pct: float, sell_friction_pct: float) -> float:
    entry_exec = entry * (1.0 + buy_friction_pct / 100.0)
    exit_exec = exit_ * (1.0 - sell_friction_pct / 100.0)
    return exit_exec / entry_exec - 1.0 if entry_exec > 0 else 0.0


def _avg(rows: list[dict], key: str) -> float | None:
    return mean(float(row[key]) for row in rows) if rows else None


def _pct(numerator: int, denominator: int) -> float | None:
    return numerator / denominator * 100.0 if denominator else None
