"""技术位目标价：量度运动 + 前高压力位 + ATR 倍数。

与投行研报"目标价"不同，这里不做盈利预测/估值建模，只用价格结构和波动率给出
参考位，方法论与现有止损体系（_compute_stop_loss）同源，都基于威科夫的量度运动
（Measured Move / Cause & Effect）思想：吸筹区间的宽度决定后续上涨的高度。

三个目标位互为参照，不是三选一：
- measured_move：箱体高度外推，最贴近威科夫方法论，需要有效箱体才能计算
- prior_high：近 N 日历史高点，最保守，缺乏箱体结构时也能算
- atr_multiple：波动率标定的兜底目标位，任何时候都能算
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFAULT_BOX_LOOKBACK_DAYS = 250
DEFAULT_PRIOR_HIGH_WINDOW = 120
DEFAULT_ATR_PERIOD = 14
DEFAULT_ATR_MULTIPLE = 3.0


@dataclass(frozen=True)
class PriceTargets:
    last_close: float
    measured_move: float | None  # 量度运动目标位（箱体高度外推）
    prior_high: float | None  # 前高压力位（近N日历史高点，若已在高点之上则为None）
    atr_multiple: float | None  # ATR倍数目标位
    conservative: float | None  # 三者中最保守（离现价最近）的一个
    aggressive: float | None  # 三者中最乐观（离现价最远）的一个


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = DEFAULT_ATR_PERIOD) -> float | None:
    """简单移动平均口径的 ATR，与 core/backtest_execution.py 的 calc_atr_from_ohlc 保持同一算法。"""
    h = pd.to_numeric(high, errors="coerce")
    low_s = pd.to_numeric(low, errors="coerce")
    c = pd.to_numeric(close, errors="coerce")
    if len(c) < period + 1:
        return None
    prev_close = c.shift(1)
    tr = pd.concat([h - low_s, (h - prev_close).abs(), (low_s - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.tail(period).mean()
    return None if pd.isna(atr) else float(atr)


def _measured_move_target(close: pd.Series, last_close: float, box_lookback_days: int) -> float | None:
    lookback = min(max(int(box_lookback_days), 2), len(close))
    if lookback < 2:
        return None
    # 箱体本身取"突破日之前"的区间，避免突破日自己把箱体上沿顶高，导致永远判定为"未突破"
    prior_box = close.tail(lookback).iloc[:-1]
    if prior_box.empty:
        return None
    box_high, box_low = float(prior_box.max()), float(prior_box.min())
    box_height = box_high - box_low
    if box_height <= 0 or last_close < box_high:
        # 箱体高度非正，或现价尚未突破箱体上沿，量度运动尚不成立
        return None
    return box_high + box_height


def _prior_high_target(close: pd.Series, last_close: float, window: int) -> float | None:
    lookback = min(max(int(window), 2), len(close))
    if lookback < 2:
        return None
    prior_high = float(close.tail(lookback).iloc[:-1].max())
    return prior_high if prior_high > last_close else None


def _atr_multiple_target(
    high: pd.Series, low: pd.Series, close: pd.Series, last_close: float, period: int, multiple: float
) -> float | None:
    atr = calc_atr(high, low, close, period)
    return None if atr is None else last_close + atr * float(multiple)


def compute_price_targets(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    *,
    box_lookback_days: int = DEFAULT_BOX_LOOKBACK_DAYS,
    prior_high_window: int = DEFAULT_PRIOR_HIGH_WINDOW,
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_multiple: float = DEFAULT_ATR_MULTIPLE,
) -> PriceTargets | None:
    """给单只股票计算参考目标价。传入的 close/high/low 需已按日期升序排序。"""
    c = pd.to_numeric(close, errors="coerce").dropna()
    if c.empty:
        return None
    last_close = float(c.iloc[-1])
    if last_close <= 0:
        return None

    measured_move = _measured_move_target(c, last_close, box_lookback_days)
    prior_high = _prior_high_target(c, last_close, prior_high_window)
    atr_target = _atr_multiple_target(high, low, c, last_close, atr_period, atr_multiple)

    candidates = [v for v in (measured_move, prior_high, atr_target) if v is not None]
    conservative = min(candidates) if candidates else None
    aggressive = max(candidates) if candidates else None
    return PriceTargets(
        last_close=last_close,
        measured_move=measured_move,
        prior_high=prior_high,
        atr_multiple=atr_target,
        conservative=conservative,
        aggressive=aggressive,
    )
