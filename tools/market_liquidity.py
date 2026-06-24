"""Market liquidity health metrics for funnel regime analysis."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MoneyFlowConfig:
    lookback: int = 20
    expand_ratio: float = 1.10
    contract_ratio: float = 0.85
    dominance_ratio: float = 1.20


@dataclass(frozen=True)
class AmountDistributionConfig:
    lookback: int = 20
    skew_threshold: float = 2.5
    thin_pass_ratio: float = 0.35


def calc_market_money_flow(
    df_map: dict[str, pd.DataFrame],
    breadth: dict | None = None,
    lookback: int | None = None,
    config: MoneyFlowConfig | None = None,
) -> dict:
    """用全市场成交额扩张/收缩和涨跌成交额分布，推断资金进退趋势。"""
    cfg = config or MoneyFlowConfig()
    resolved_lookback = max(int(lookback if lookback is not None else cfg.lookback), 2)
    snapshots = [
        item for item in (_symbol_money_snapshot(df, resolved_lookback) for df in df_map.values()) if item is not None
    ]
    totals = _money_flow_totals(snapshots)
    amount_ratio = _safe_ratio(float(totals["total_amount"]), float(totals["mean_amount"]))
    amount_ratio_3_20 = _safe_ratio(float(totals["recent3_amount"]), float(totals["mean_amount"]))
    amount_change_pct = _safe_ratio(float(totals["total_amount"]), float(totals["prev_total_amount"]))
    up_down_ratio = _safe_ratio(float(totals["up_amount"]), float(totals["down_amount"]))
    breadth_delta = breadth.get("delta_pct") if breadth else None
    state = _classify_money_flow(amount_ratio, up_down_ratio, breadth_delta, cfg)
    score = _money_flow_score(amount_ratio, float(totals["up_amount"]), float(totals["down_amount"]), breadth_delta)
    trend = "entry" if score >= 20 else "retreat" if score <= -20 else "neutral"
    return _money_flow_result(
        totals, amount_ratio, amount_ratio_3_20, amount_change_pct, up_down_ratio, state, trend, score, breadth
    )


def calc_amount_distribution_health(
    df_map: dict[str, pd.DataFrame],
    min_avg_amount_wan: float,
    lookback: int | None = None,
    config: AmountDistributionConfig | None = None,
) -> dict:
    """检查全市场成交额是否过度集中，避免均值被少数龙头抬高。"""
    cfg = config or AmountDistributionConfig()
    resolved_lookback = max(int(lookback if lookback is not None else cfg.lookback), 2)
    values = [
        value
        for value in (_symbol_avg_amount(df, resolved_lookback) for df in df_map.values())
        if value is not None and value > 0
    ]
    if not values:
        return _empty_amount_distribution(cfg)
    series = pd.Series(values, dtype=float)
    return _amount_distribution_result(series, min_avg_amount_wan, resolved_lookback, cfg)


def _money_flow_result(
    totals: dict,
    amount_ratio: float | None,
    amount_ratio_3_20: float | None,
    amount_change_pct: float | None,
    up_down_ratio: float | None,
    state: str,
    trend: str,
    score: float,
    breadth: dict | None,
) -> dict:
    return {
        "state": state,
        "trend": trend,
        "score": score,
        "sample_size": totals["sample_size"],
        "total_amount_yi": round(float(totals["total_amount"]) / 1e8, 2),
        "prev_total_amount_yi": round(float(totals["prev_total_amount"]) / 1e8, 2),
        "amount_ratio_1_20": None if amount_ratio is None else round(amount_ratio, 3),
        "amount_ratio_3_20": None if amount_ratio_3_20 is None else round(amount_ratio_3_20, 3),
        "amount_change_pct": None if amount_change_pct is None else round((amount_change_pct - 1.0) * 100.0, 2),
        "up_amount_yi": round(float(totals["up_amount"]) / 1e8, 2),
        "down_amount_yi": round(float(totals["down_amount"]) / 1e8, 2),
        "up_down_amount_ratio": None if up_down_ratio is None else round(up_down_ratio, 3),
        "advancing_count": totals["advancing_count"],
        "declining_count": totals["declining_count"],
        "summary": _money_flow_summary(state, totals, amount_ratio, up_down_ratio, breadth or {}),
    }


def _amount_distribution_result(
    series: pd.Series,
    min_avg_amount_wan: float,
    lookback: int,
    config: AmountDistributionConfig,
) -> dict:
    threshold = float(min_avg_amount_wan) * 10000
    mean_amount = float(series.mean())
    median_amount = float(series.median())
    skewness = float(series.skew()) if len(series) >= 3 else 0.0
    pass_ratio = float((series >= threshold).mean())
    dry_ratio = float((series < threshold * 0.5).mean())
    median_mean = _safe_ratio(median_amount, mean_amount) or 0.0
    p20 = float(series.quantile(0.2))
    p80 = float(series.quantile(0.8))
    p80_p20 = _safe_ratio(p80, p20)
    state = _amount_distribution_state(pass_ratio, median_mean, skewness, config)
    return {
        "state": state,
        "summary": _amount_distribution_summary(state, len(series), skewness, pass_ratio, median_mean),
        "sample_size": len(series),
        "lookback": max(int(lookback), 2),
        "mean_amount_yi": round(mean_amount / 1e8, 3),
        "median_amount_yi": round(median_amount / 1e8, 3),
        "median_mean_ratio": round(median_mean, 3),
        "p80_p20_ratio": None if p80_p20 is None else round(p80_p20, 3),
        "skewness": round(skewness, 3),
        "pass_ratio_pct": round(pass_ratio * 100.0, 2),
        "dry_ratio_pct": round(dry_ratio * 100.0, 2),
    }


def _sorted_daily_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "date" in work.columns:
        work = work.sort_values("date")
    return work.reset_index(drop=True)


def _symbol_money_snapshot(df: pd.DataFrame, lookback: int) -> dict | None:
    if df is None or df.empty or "amount" not in df.columns:
        return None
    work = _sorted_daily_frame(df)
    close = pd.to_numeric(work.get("close"), errors="coerce")
    amount = pd.to_numeric(work.get("amount"), errors="coerce")
    valid = pd.DataFrame({"close": close, "amount": amount}).dropna()
    if len(valid) < 2:
        return None
    latest_amount = float(valid["amount"].iloc[-1])
    if latest_amount <= 0:
        return None
    positive_amount = valid["amount"][valid["amount"] > 0]
    return {
        "pct": _latest_pct(valid),
        "latest_amount": latest_amount,
        "prev_amount": float(valid["amount"].iloc[-2]) if float(valid["amount"].iloc[-2]) > 0 else 0.0,
        "mean_amount": float(positive_amount.tail(lookback).mean()) if not positive_amount.empty else 0.0,
        "recent3_amount": float(positive_amount.tail(3).mean()) if not positive_amount.empty else 0.0,
    }


def _latest_pct(valid: pd.DataFrame) -> float:
    prev_close = float(valid["close"].iloc[-2])
    latest_close = float(valid["close"].iloc[-1])
    return (latest_close / prev_close - 1.0) * 100.0 if prev_close > 0 else 0.0


def _money_flow_totals(snapshots: list[dict]) -> dict[str, float | int]:
    up_amount = sum(item["latest_amount"] for item in snapshots if item["pct"] > 0)
    down_amount = sum(item["latest_amount"] for item in snapshots if item["pct"] < 0)
    return {
        "sample_size": len(snapshots),
        "total_amount": sum(item["latest_amount"] for item in snapshots),
        "prev_total_amount": sum(item["prev_amount"] for item in snapshots),
        "mean_amount": sum(item["mean_amount"] for item in snapshots),
        "recent3_amount": sum(item["recent3_amount"] for item in snapshots),
        "up_amount": up_amount,
        "down_amount": down_amount,
        "advancing_count": sum(1 for item in snapshots if item["pct"] > 0),
        "declining_count": sum(1 for item in snapshots if item["pct"] < 0),
    }


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator and denominator > 0 else None


def _classify_money_flow(
    amount_ratio: float | None,
    up_down_ratio: float | None,
    breadth_delta: float | None,
    config: MoneyFlowConfig,
) -> str:
    expanded = amount_ratio is not None and amount_ratio >= config.expand_ratio
    contracted = amount_ratio is not None and amount_ratio <= config.contract_ratio
    up_dominant = up_down_ratio is not None and up_down_ratio >= config.dominance_ratio
    down_dominant = up_down_ratio is not None and up_down_ratio <= 1.0 / config.dominance_ratio
    breadth_ok = breadth_delta is None or breadth_delta >= 0
    breadth_bad = breadth_delta is not None and breadth_delta < 0
    if expanded and up_dominant and breadth_ok:
        return "主力进场"
    if expanded and down_dominant and breadth_bad:
        return "主力撤退"
    if expanded:
        return "放量分歧"
    if contracted and up_dominant:
        return "缩量反弹"
    if contracted:
        return "缩量观望"
    if up_dominant:
        return "资金偏进"
    if down_dominant:
        return "资金偏撤"
    return "资金均衡"


def _money_flow_score(
    amount_ratio: float | None, up_amount: float, down_amount: float, breadth_delta: float | None
) -> float:
    total_directional = up_amount + down_amount
    direction = (up_amount - down_amount) / total_directional if total_directional > 0 else 0.0
    expansion = (amount_ratio - 1.0) if amount_ratio is not None else 0.0
    breadth_part = (breadth_delta or 0.0) / 20.0
    return round(direction * 60.0 + expansion * 35.0 + breadth_part * 20.0, 1)


def _money_flow_summary(
    state: str, totals: dict, amount_ratio: float | None, up_down_ratio: float | None, breadth: dict
) -> str:
    if not totals["sample_size"]:
        return "资金趋势：样本不足，暂不判断主力进退。"
    ratio_text = f"{amount_ratio:.2f}x" if amount_ratio is not None else "未知"
    ud_text = f"{up_down_ratio:.2f}x" if up_down_ratio is not None else "无下跌成交额"
    breadth_delta = breadth.get("delta_pct") if breadth else None
    breadth_text = f"，广度变化 {float(breadth_delta):+.1f}pct" if breadth_delta is not None else ""
    total_yi = float(totals["total_amount"]) / 1e8
    return f"{state}：全市场成交额 {total_yi:.0f}亿，为20日均额 {ratio_text}；上涨/下跌成交额 {ud_text}{breadth_text}。"


def _symbol_avg_amount(df: pd.DataFrame, lookback: int) -> float | None:
    if df is None or df.empty or "amount" not in df.columns:
        return None
    work = _sorted_daily_frame(df)
    amount = pd.to_numeric(work.get("amount"), errors="coerce").dropna()
    amount = amount[amount > 0].tail(max(int(lookback), 2))
    if amount.empty:
        return None
    return float(amount.mean())


def _empty_amount_distribution(config: AmountDistributionConfig) -> dict:
    return {
        "state": "unknown",
        "summary": "成交额分布：样本不足，暂不判断流动性偏度。",
        "sample_size": 0,
        "lookback": max(int(config.lookback), 2),
        "mean_amount_yi": None,
        "median_amount_yi": None,
        "median_mean_ratio": None,
        "p80_p20_ratio": None,
        "skewness": None,
        "pass_ratio_pct": None,
        "dry_ratio_pct": None,
    }


def _amount_distribution_state(
    pass_ratio: float,
    median_mean: float,
    skewness: float,
    config: AmountDistributionConfig,
) -> str:
    if pass_ratio < config.thin_pass_ratio or median_mean < 0.35:
        return "thin"
    if skewness >= config.skew_threshold and median_mean < 0.55:
        return "concentrated"
    return "healthy"


def _amount_distribution_summary(state: str, sample: int, skew: float, pass_ratio: float, median_mean: float) -> str:
    state_label = {"healthy": "健康", "concentrated": "集中", "thin": "偏弱"}.get(state, "未知")
    return (
        f"成交额分布{state_label}：样本{sample}只，偏度{skew:.2f}，"
        f"达标占比{pass_ratio * 100:.1f}%，中位/均值{median_mean:.2f}。"
    )
