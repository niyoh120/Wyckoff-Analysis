"""Replay HK/US backtest trades with explicit entry and partial-exit rules.

港股没有涨跌停，价格不连续风险主要来自合股/拆股/供股（而非美股的极端单日暴涨暴跌），
且仙股/流动性陷阱是港股特有的信号污染源，因此复用 core.hk_risk_filter 做统一风控；
美股改用基于单日涨跌幅与开高收比例的 splitlike 启发式判定。策略规则本身（Wyckoff
SOS/EVR/LPS 触发 + 分批止盈）与市场无关，两地共用同一份六策略矩阵，
市场特定行为集中在 MarketRules，便于跨市场横向对比。
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Literal

import pandas as pd

from core.wyckoff_engine import dollar_volume_series
from utils.safe import safe_float as _safe_float

Market = Literal["hk", "us"]


@dataclass(frozen=True)
class StrategySpec:
    id: str
    name: str
    description: str
    entry_rule: str
    pullback_pct: float
    target_multipliers: tuple[float, float]
    fallback_rule: str
    max_days: int


@dataclass(frozen=True)
class ReplayTrade:
    signal_date: str
    entry_date: str
    exit_date: str
    code: str
    name: str
    buy_price: float
    exit_value: float
    ret_pct: float
    trigger: str
    score: float


@dataclass(frozen=True)
class SignalCandidate:
    signal_date: str
    entry_date: str
    code: str
    name: str
    entry_close: float
    trigger: str
    score: float


STRATEGIES = (
    StrategySpec(
        "s1_open_2x3x", "策略1", "开盘买入，2x/3x各卖50%，未成交按现价", "open", 0.0, (2.0, 3.0), "mark_to_market", 20
    ),
    StrategySpec(
        "s2_pullback30_2x3x",
        "策略2",
        "回撤30%买入，2x/3x各卖50%；满3日未成交按原价，不满3日按现价",
        "pullback",
        30.0,
        (2.0, 3.0),
        "original_or_mark",
        3,
    ),
    StrategySpec(
        "s3_pullback10_12x15x",
        "策略3",
        "回撤10%买入，1.2x/1.5x各卖50%；满3日剩余按最后一日1.2x开盘价，不满3日按现价",
        "pullback",
        10.0,
        (1.2, 1.5),
        "last_day_1_2x_open_or_mark",
        3,
    ),
    StrategySpec(
        "patch_a_open_12x15x",
        "补充A",
        "开盘买入，1.2x/1.5x各卖50%，未成交按3日后开盘价",
        "open",
        0.0,
        (1.2, 1.5),
        "open_after_3d",
        3,
    ),
    StrategySpec(
        "patch_b_pullback10_11x13x",
        "补充B",
        "回撤10%买入，1.1x/1.3x各卖50%，未成交按3日后开盘价",
        "pullback",
        10.0,
        (1.1, 1.3),
        "open_after_3d",
        3,
    ),
    StrategySpec(
        "patch_c_pullback20_12x15x",
        "补充C",
        "回撤20%买入，1.2x/1.5x各卖50%，未成交按3日后开盘价",
        "pullback",
        20.0,
        (1.2, 1.5),
        "open_after_3d",
        3,
    ),
)


MIN_LOOKBACK_ROWS = 80


@dataclass(frozen=True)
class MarketRules:
    """市场特定的风控口径与信号触发阈值，主回放流程完全共享。"""

    market: Market
    min_price: float
    max_price: float
    min_dollar_volume: float
    sos_pct: float
    sos_vol_ratio: float
    is_row_blocked: Callable[[pd.DataFrame, int], bool]


def _hk_risk_blocked(candles: pd.DataFrame, idx: int) -> bool:
    """基于 core.hk_risk_filter 判定该交易日是否触发港股风险（仙股/流动性/极端波幅/价格跳变）。

    TickFlow 港股历史 K 线的 amount 字段恒为 0（数据源限制），dollar_volume_series
    会回退为 close*volume 口径，否则所有交易日都会被误判为流动性不足。
    """
    from core.hk_risk_filter import classify_hk_risk

    if idx <= 0 or idx >= len(candles):
        return False
    row = candles.iloc[idx]
    prev_close = _safe_float(candles.iloc[idx - 1].get("close"))
    window = candles.iloc[max(0, idx - 20) : idx]
    turnover = dollar_volume_series(window)
    avg_turnover = float(turnover.mean()) if not turnover.empty else math.inf
    flags = classify_hk_risk(
        close=_safe_float(row.get("close")),
        open_=_safe_float(row.get("open")),
        prev_close=prev_close,
        pct_chg=_safe_float(row.get("pct_chg")),
        avg_turnover_hkd=avg_turnover,
    )
    return flags.blocked


_MAX_SPLITLIKE_DAILY_PCT = 120.0
_MAX_SPLITLIKE_PRICE_RATIO = 4.0


def _us_splitlike_blocked(candles: pd.DataFrame, idx: int) -> bool:
    """美股无统一风控 API，改用单日涨跌幅与开高收对前收比例识别拆股/合股导致的价格跳变。"""
    row = candles.iloc[idx]
    prev_close = _safe_float(candles.iloc[idx - 1].get("close"))
    open_px = _safe_float(row.get("open"))
    close_px = _safe_float(row.get("close"))
    pct = _safe_float(row.get("pct_chg"))
    if abs(pct) > _MAX_SPLITLIKE_DAILY_PCT or prev_close <= 0:
        return abs(pct) > _MAX_SPLITLIKE_DAILY_PCT
    open_ratio = open_px / prev_close if open_px > 0 else 1.0
    close_ratio = close_px / prev_close if close_px > 0 else 1.0
    return (
        open_ratio > _MAX_SPLITLIKE_PRICE_RATIO
        or close_ratio > _MAX_SPLITLIKE_PRICE_RATIO
        or open_ratio < 1.0 / _MAX_SPLITLIKE_PRICE_RATIO
        or close_ratio < 1.0 / _MAX_SPLITLIKE_PRICE_RATIO
    )


MARKET_RULES: dict[Market, MarketRules] = {
    "hk": MarketRules(
        market="hk",
        min_price=1.0,  # 港股仙股门槛：低于此价的走势容易被供股/合股操纵
        max_price=10_000.0,
        min_dollar_volume=2_000_000.0,  # 港股日均成交额门槛，与漏斗侧 hk_risk_filter 保持一致
        sos_pct=7.0,
        sos_vol_ratio=3.0,
        is_row_blocked=_hk_risk_blocked,
    ),
    "us": MarketRules(
        market="us",
        min_price=1.0,
        max_price=1_000.0,
        min_dollar_volume=1_000_000.0,
        sos_pct=5.0,
        sos_vol_ratio=1.8,
        is_row_blocked=_us_splitlike_blocked,
    ),
}


def _parse_date(value: Any) -> date | None:
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def _load_hist_map(snapshot_dir: Path) -> dict[str, pd.DataFrame]:
    hist_path = snapshot_dir / "hist_full.csv.gz"
    df = pd.read_csv(hist_path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    return {str(sym): g.sort_values("date").reset_index(drop=True) for sym, g in df.groupby("symbol")}


def _load_name_map(snapshot_dir: Path) -> dict[str, str]:
    path = snapshot_dir / "name_map.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v or k) for k, v in data.items()} if isinstance(data, dict) else {}


def _trade_calendar(snapshot_dir: Path, hist_map: dict[str, pd.DataFrame]) -> list[date]:
    bench_path = snapshot_dir / "benchmark_main.csv"
    if bench_path.exists():
        bench = pd.read_csv(bench_path)
        dates = pd.to_datetime(bench.get("date"), errors="coerce").dt.date.dropna().tolist()
        if dates:
            return sorted(set(dates))
    return sorted({d for frame in hist_map.values() for d in frame["date"].tolist()})


def _find_idx(candles: pd.DataFrame, target: date) -> int | None:
    dates = candles["date"].tolist()
    for idx, day in enumerate(dates):
        if day >= target:
            return idx
    return None


def _signal_triggers(stats: dict[str, float], rules: MarketRules) -> tuple[list[str], float]:
    triggers: list[str] = []
    score = stats["pct"] * 1.2 + min(stats["vol_ratio"], 8.0) * 5.0 + stats["range_pos"] * 18.0
    if stats["pct"] >= rules.sos_pct and stats["vol_ratio"] >= rules.sos_vol_ratio and stats["breakout_ratio"] >= 0.98:
        triggers.append("SOS")
        score += 30.0
    if stats["vol_ratio"] >= 2.0 and stats["pct"] >= -2.0 and stats["range_pos"] >= 0.55:
        triggers.append("EVR")
        score += 18.0
    if _is_lps_like(stats):
        triggers.append("LPS")
        score += 14.0
    return triggers, score


def _is_lps_like(stats: dict[str, float]) -> bool:
    return (
        stats["ma20"] > 0
        and stats["ma50"] > 0
        and stats["ma20"] >= stats["ma50"] * 0.96
        and 0.06 <= stats["pullback_from_high"] <= 0.30
        and -2.5 <= stats["pct"] <= 4.0
        and stats["vol_ratio"] <= 1.5
        and stats["range_pos"] >= 0.45
    )


def _has_risk_blocked_window(candles: pd.DataFrame, start_idx: int, end_idx: int, rules: MarketRules) -> bool:
    return any(
        rules.is_row_blocked(candles, pos) for pos in range(max(1, start_idx), min(end_idx, len(candles) - 1) + 1)
    )


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _symbol_feature_frame(candles: pd.DataFrame) -> pd.DataFrame:
    close = _numeric_series(candles, "close")
    high = _numeric_series(candles, "high")
    low = _numeric_series(candles, "low")
    volume = _numeric_series(candles, "volume")
    prev_close = close.shift(1)
    high_20 = high.shift(1).rolling(20, min_periods=20).max()
    low_20 = low.rolling(20, min_periods=20).min()
    vol_mean = volume.shift(1).rolling(20, min_periods=20).mean()
    range_width = pd.concat([(high_20 - low_20), close * 0.01], axis=1).max(axis=1)
    pct = (close / prev_close - 1.0) * 100.0
    dollar_volume = dollar_volume_series(candles).reindex(candles.index)
    return pd.DataFrame(
        {
            "date": candles["date"],
            "close": close,
            "pct": pct,
            "vol_ratio": volume / vol_mean,
            "range_pos": (close - low_20) / range_width,
            "breakout_ratio": close / high_20,
            "ma20": close.rolling(20, min_periods=20).mean(),
            "ma50": close.rolling(50, min_periods=50).mean(),
            "pullback_from_high": (high_20 - close) / high_20,
            "dollar_volume": dollar_volume,
        }
    )


def _generate_signal_rows(
    hist_map: dict[str, pd.DataFrame],
    name_map: dict[str, str],
    calendar: list[date],
    start: date,
    end: date,
    top_n: int,
    rules: MarketRules,
) -> list[dict[str, Any]]:
    next_by_date = {day: calendar[idx + 1] for idx, day in enumerate(calendar[:-1])}
    by_day: dict[date, list[SignalCandidate]] = {}
    for code, candles in hist_map.items():
        _collect_symbol_candidates(code, candles, name_map.get(code, code), next_by_date, start, end, by_day, rules)

    rows: list[dict[str, Any]] = []
    for signal_date in calendar:
        if not start <= signal_date < end:
            continue
        day_rows = sorted(by_day.get(signal_date, []), key=lambda item: item.score, reverse=True)
        rows.extend(asdict(item) for item in day_rows[: max(int(top_n), 1)])
    return rows


def _collect_symbol_candidates(
    code: str,
    candles: pd.DataFrame,
    name: str,
    next_by_date: dict[date, date],
    start: date,
    end: date,
    by_day: dict[date, list[SignalCandidate]],
    rules: MarketRules,
) -> None:
    features = _symbol_feature_frame(candles)
    mask = (
        (features.index >= MIN_LOOKBACK_ROWS - 1)
        & (features["date"] >= start)
        & (features["date"] < end)
        & features["close"].between(rules.min_price, rules.max_price)
        & (features["dollar_volume"] >= rules.min_dollar_volume)
    )
    for row_idx, row in features[mask].dropna().iterrows():
        if rules.is_row_blocked(candles, int(row_idx)):
            continue
        signal_date = row["date"]
        entry_date = next_by_date.get(signal_date)
        if entry_date is None or entry_date > end:
            continue
        stats = _stats_from_feature_row(row)
        triggers, score = _signal_triggers(stats, rules)
        if triggers:
            by_day.setdefault(signal_date, []).append(
                SignalCandidate(
                    signal_date=signal_date.isoformat(),
                    entry_date=entry_date.isoformat(),
                    code=code,
                    name=name,
                    entry_close=round(_safe_float(row["close"]), 4),
                    trigger="+".join(triggers),
                    score=round(score, 4),
                )
            )


def _stats_from_feature_row(row: pd.Series) -> dict[str, float]:
    return {
        "pct": _safe_float(row["pct"]),
        "vol_ratio": _safe_float(row["vol_ratio"]),
        "range_pos": _safe_float(row["range_pos"]),
        "breakout_ratio": _safe_float(row["breakout_ratio"]),
        "ma20": _safe_float(row["ma20"]),
        "ma50": _safe_float(row["ma50"]),
        "pullback_from_high": _safe_float(row["pullback_from_high"]),
    }


def _entry(strategy: StrategySpec, candles: pd.DataFrame, idx: int, base_price: float) -> tuple[int, float] | None:
    if strategy.entry_rule == "open":
        return idx, _safe_float(candles.iloc[idx]["open"], base_price)
    target = base_price * (1.0 - strategy.pullback_pct / 100.0)
    last_idx = min(idx + strategy.max_days, len(candles) - 1)
    for pos in range(idx, last_idx + 1):
        row = candles.iloc[pos]
        if _safe_float(row["low"], math.inf) <= target:
            open_px = _safe_float(row["open"], target)
            return pos, min(open_px, target)
    return None


def _fallback_exit(strategy: StrategySpec, candles: pd.DataFrame, idx: int, buy_price: float) -> tuple[int, float]:
    row = candles.iloc[idx]
    if strategy.fallback_rule == "last_day_1_2x_open_or_mark":
        return idx, _safe_float(row["open"], buy_price) * 1.2
    if strategy.fallback_rule == "open_after_3d":
        return idx, _safe_float(row["open"], buy_price)
    return idx, _safe_float(row["close"], buy_price)


def _exit(strategy: StrategySpec, candles: pd.DataFrame, buy_idx: int, buy_price: float) -> tuple[int, float] | None:
    start_idx = buy_idx + 1
    if start_idx >= len(candles):
        return None
    end_idx = min(buy_idx + strategy.max_days, len(candles) - 1)
    proceeds = 0.0
    remaining = 1.0
    latest_exit_idx = start_idx
    scan_idx = start_idx
    for multiple in strategy.target_multipliers:
        target = buy_price * multiple
        hit_idx = _target_hit_idx(candles, scan_idx, end_idx, target)
        if hit_idx is None:
            continue
        proceeds += 0.5 * target
        remaining -= 0.5
        latest_exit_idx = hit_idx
        scan_idx = hit_idx
    if remaining > 0:
        fallback_idx, fallback_px = _fallback_exit(strategy, candles, end_idx, buy_price)
        proceeds += remaining * fallback_px
        latest_exit_idx = max(latest_exit_idx, fallback_idx)
    return latest_exit_idx, proceeds


def _target_hit_idx(candles: pd.DataFrame, start_idx: int, end_idx: int, target: float) -> int | None:
    for pos in range(start_idx, end_idx + 1):
        if _safe_float(candles.iloc[pos]["high"], -math.inf) >= target:
            return pos
    return None


def _replay_one(
    row: dict[str, Any], hist_map: dict[str, pd.DataFrame], strategy: StrategySpec, rules: MarketRules
) -> ReplayTrade | None:
    code = str(row.get("code") or "").strip()
    entry_date = _parse_date(row.get("entry_date"))
    base_price = _safe_float(row.get("entry_close"))
    candles = hist_map.get(code)
    if candles is None or entry_date is None or base_price <= 0:
        return None
    idx = _find_idx(candles, entry_date)
    if idx is None:
        return None
    entry = _entry(strategy, candles, idx, base_price)
    if entry is None:
        if _has_risk_blocked_window(candles, idx + 1, min(idx + strategy.max_days, len(candles) - 1), rules):
            return None
        return _unfilled_trade(row, candles, idx, strategy, base_price)
    buy_idx, buy_price = entry
    if _has_risk_blocked_window(candles, idx + 1, min(buy_idx + strategy.max_days, len(candles) - 1), rules):
        return None
    exit_result = _exit(strategy, candles, buy_idx, buy_price)
    if exit_result is None or buy_price <= 0:
        return None
    exit_idx, exit_value = exit_result
    return _trade_from_result(row, candles, buy_idx, exit_idx, buy_price, exit_value)


def _unfilled_trade(
    row: dict[str, Any],
    candles: pd.DataFrame,
    idx: int,
    strategy: StrategySpec,
    base_price: float,
) -> ReplayTrade:
    fallback_idx = min(idx + strategy.max_days, len(candles) - 1)
    fallback_row = candles.iloc[fallback_idx]
    full_window = fallback_idx >= idx + strategy.max_days
    if strategy.fallback_rule == "original_or_mark" and full_window:
        exit_value = base_price
    elif strategy.fallback_rule == "open_after_3d" and full_window:
        exit_value = _safe_float(fallback_row.get("open"), base_price)
    else:
        exit_value = _safe_float(fallback_row.get("close"), base_price)
    trigger = str(row.get("trigger") or "")
    return ReplayTrade(
        signal_date=str(row.get("signal_date") or ""),
        entry_date=str(row.get("entry_date") or candles.iloc[idx]["date"]),
        exit_date=str(fallback_row["date"]),
        code=str(row.get("code") or ""),
        name=str(row.get("name") or row.get("code") or ""),
        buy_price=round(base_price, 4),
        exit_value=round(exit_value, 4),
        ret_pct=round((exit_value / base_price - 1.0) * 100.0, 4) if base_price > 0 else 0.0,
        trigger=f"{trigger}|NO_FILL" if trigger else "NO_FILL",
        score=_safe_float(row.get("score")),
    )


def _load_input_rows(
    trades_csv: str,
    hist_map: dict[str, pd.DataFrame],
    snapshot_dir: Path,
    *,
    start: str,
    end: str,
    top_n: str,
    rules: MarketRules,
) -> list[dict[str, Any]]:
    if trades_csv:
        path = Path(trades_csv)
        if path.exists() and path.stat().st_size > 0:
            try:
                rows = pd.read_csv(path).to_dict("records")
            except pd.errors.EmptyDataError:
                rows = []
            if rows:
                return rows
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date is None or end_date is None:
        raise ValueError("start/end must be valid dates")
    return _generate_signal_rows(
        hist_map,
        _load_name_map(snapshot_dir),
        _trade_calendar(snapshot_dir, hist_map),
        start_date,
        end_date,
        int(top_n),
        rules,
    )


def _trade_from_result(
    row: dict[str, Any], candles: pd.DataFrame, buy_idx: int, exit_idx: int, buy_price: float, exit_value: float
) -> ReplayTrade:
    return ReplayTrade(
        signal_date=str(row.get("signal_date") or ""),
        entry_date=str(candles.iloc[buy_idx]["date"]),
        exit_date=str(candles.iloc[exit_idx]["date"]),
        code=str(row.get("code") or ""),
        name=str(row.get("name") or row.get("code") or ""),
        buy_price=round(buy_price, 4),
        exit_value=round(exit_value, 4),
        ret_pct=round((exit_value / buy_price - 1.0) * 100.0, 4),
        trigger=str(row.get("trigger") or ""),
        score=_safe_float(row.get("score")),
    )


def _max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    nav = 1.0
    peak = 1.0
    mdd = 0.0
    for ret in returns:
        nav *= 1.0 + ret / 100.0
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1.0)
    return mdd * 100.0


def _summary(
    strategy: StrategySpec, trades: list[ReplayTrade], period: dict[str, str], top_n: str, market: Market
) -> dict[str, Any]:
    returns = [t.ret_pct for t in trades]
    std = stdev(returns) if len(returns) > 1 else 0.0
    sharpe = mean(returns) / std if std > 0 else None
    total = (math.prod(1.0 + r / 100.0 for r in returns) - 1.0) * 100.0 if returns else None
    return {
        "source": f"local_{market}_strategy_replay",
        "period_key": period["key"],
        "period_label": period["label"],
        "start": period["start"],
        "end": period["end"],
        "top_n": int(top_n),
        "board": market,
        "execution_strategy": asdict(strategy) | {"sell_after_buy_only": True, "target_scan_start": "after_entry"},
        "strategy_id": strategy.id,
        "strategy_name": strategy.name,
        "strategy_desc": strategy.description,
        "trades": len(returns),
        "win_rate_pct": (sum(1 for r in returns if r > 0) / len(returns) * 100.0) if returns else None,
        "avg_ret_pct": mean(returns) if returns else None,
        "median_ret_pct": median(returns) if returns else None,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": _max_drawdown(returns),
        "portfolio_total_ret_pct": total,
    }


def _write_outputs(out_dir: Path, strategy: StrategySpec, summary: dict[str, Any], trades: list[ReplayTrade]) -> None:
    strategy_dir = out_dir / strategy.id
    strategy_dir.mkdir(parents=True, exist_ok=True)
    (strategy_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (strategy_dir / "trades.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(ReplayTrade.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(t) for t in trades)


def run_strategy_replay(args, *, market: Market) -> int:
    rules = MARKET_RULES[market]
    snapshot_dir = Path(args.snapshot_dir)
    hist_map = _load_hist_map(snapshot_dir)
    rows = _load_input_rows(
        args.trades_csv,
        hist_map,
        snapshot_dir,
        start=args.start,
        end=args.end,
        top_n=args.top_n,
        rules=rules,
    )
    print(f"[{market}-replay] input signals={len(rows)}")
    period = {"key": args.period_key, "label": args.period_label, "start": args.start, "end": args.end}
    for strategy in STRATEGIES:
        trades = [t for row in rows if (t := _replay_one(row, hist_map, strategy, rules)) is not None]
        summary = _summary(strategy, trades, period, str(args.top_n), market)
        _write_outputs(Path(args.output_dir), strategy, summary, trades)
        print(f"[{market}-replay] {strategy.name}: trades={len(trades)}, sharpe={summary.get('sharpe_ratio')}")
    return 0
