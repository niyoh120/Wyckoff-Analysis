"""港股专属风险识别（纯计算层）。

港股没有涨跌停制度，Wyckoff 的 Effort vs Result 假设在这里不会被价格截断打断，
但港股市场结构风险集中在另外两类：
- 仙股/老千股：长期股价极低、频繁供股/合股/大比例配股摊薄，K 线上表现为持续
  阴跌 + 偶发单日暴涨暴跌，这类走势会污染 Wyckoff 形态识别（把摊薄下跌误判为
  派发下跌，把合股拉升误判为吸筹突破）。
- 极端波幅/流动性异常：单日涨跌幅远超正常港股波动范围（例如合股、拆股或财技
  操作导致的价格跳变），同样不能被当作有效的 SOS/Spring 信号。

本模块只做定性识别，不做买卖决策，供漏斗筛选层和回测层共用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PENNY_STOCK_PRICE_HKD = 1.0  # 港股仙股价格粗筛门槛（低于此价更容易被财技操纵）
MIN_LIQUID_TURNOVER_HKD = 2_000_000.0  # 日均成交额低于此值视为流动性不足
EXTREME_DAILY_MOVE_PCT = 50.0  # 单日涨跌幅超过此值，大概率是合股/拆股/财技跳空
SPLITLIKE_PRICE_RATIO = 3.0  # 开盘或收盘相对前收的比值超过此倍数，判定为价格不连续


@dataclass(frozen=True)
class HkRiskFlags:
    """单只港股在某个交易日的风险画像。"""

    is_penny_stock: bool  # 收盘价低于仙股门槛
    is_illiquid: bool  # 近期日均成交额低于流动性门槛
    is_extreme_move: bool  # 当日涨跌幅超过正常波动范围（疑似合股/拆股/财技）
    is_price_discontinuous: bool  # 开盘或收盘价相对前收出现跳变式不连续

    @property
    def blocked(self) -> bool:
        """任一风险标记命中，即认为该信号不可信，应从候选池剔除。"""
        return self.is_penny_stock or self.is_illiquid or self.is_extreme_move or self.is_price_discontinuous


def is_penny_stock(close: float, *, price_floor: float = PENNY_STOCK_PRICE_HKD) -> bool:
    """收盘价低于门槛视为仙股候选，港股仙股常见财技手法（供股/合股）会扭曲形态。"""
    return close > 0 and close < price_floor


def is_illiquid(avg_turnover_hkd: float, *, min_turnover: float = MIN_LIQUID_TURNOVER_HKD) -> bool:
    """近期日均成交额低于门槛，判定为流动性不足，买卖价差和冲击成本会失真。"""
    return avg_turnover_hkd < min_turnover


def is_extreme_daily_move(pct_chg: float, *, max_move_pct: float = EXTREME_DAILY_MOVE_PCT) -> bool:
    """单日涨跌幅超过正常港股波动范围，大概率是合股/拆股而非真实买卖力量变化。"""
    return abs(pct_chg) > max_move_pct


def is_price_discontinuous(
    open_: float,
    close: float,
    prev_close: float,
    *,
    max_ratio: float = SPLITLIKE_PRICE_RATIO,
) -> bool:
    """开盘/收盘相对前收比值超过阈值，判定为价格跳变（合股/拆股/供股除权未复权）。"""
    if prev_close <= 0:
        return False
    open_ratio = open_ / prev_close if open_ > 0 else 1.0
    close_ratio = close / prev_close if close > 0 else 1.0
    return (
        open_ratio > max_ratio
        or close_ratio > max_ratio
        or open_ratio < 1.0 / max_ratio
        or close_ratio < 1.0 / max_ratio
    )


def classify_hk_risk(
    *,
    close: float,
    open_: float = 0.0,
    prev_close: float = 0.0,
    pct_chg: float = 0.0,
    avg_turnover_hkd: float = math.inf,
    price_floor: float = PENNY_STOCK_PRICE_HKD,
    min_turnover: float = MIN_LIQUID_TURNOVER_HKD,
    max_move_pct: float = EXTREME_DAILY_MOVE_PCT,
    max_splitlike_ratio: float = SPLITLIKE_PRICE_RATIO,
) -> HkRiskFlags:
    """汇总仙股/流动性/极端波幅/价格不连续四项风险标记。"""
    return HkRiskFlags(
        is_penny_stock=is_penny_stock(close, price_floor=price_floor),
        is_illiquid=is_illiquid(avg_turnover_hkd, min_turnover=min_turnover),
        is_extreme_move=is_extreme_daily_move(pct_chg, max_move_pct=max_move_pct),
        is_price_discontinuous=is_price_discontinuous(open_, close, prev_close, max_ratio=max_splitlike_ratio),
    )


def describe_hk_risk(flags: HkRiskFlags | None) -> str:
    """生成人类可读的风险描述，供诊断文本/LLM prompt/飞书报告使用。"""
    if flags is None:
        return ""
    reasons = []
    if flags.is_penny_stock:
        reasons.append(f"股价低于 {PENNY_STOCK_PRICE_HKD:.1f} 港元，疑似仙股/老千股，易被供股合股摊薄操纵")
    if flags.is_illiquid:
        reasons.append("近期日均成交额过低，流动性不足，买卖价差和冲击成本可能失真")
    if flags.is_extreme_move:
        reasons.append(f"单日涨跌幅超过 {EXTREME_DAILY_MOVE_PCT:.0f}%，疑似合股/拆股而非真实买卖力量")
    if flags.is_price_discontinuous:
        reasons.append("开盘/收盘价相对前收跳变，疑似未复权的合股/拆股/供股除权")
    return "；".join(reasons)


__all__ = [
    "EXTREME_DAILY_MOVE_PCT",
    "MIN_LIQUID_TURNOVER_HKD",
    "PENNY_STOCK_PRICE_HKD",
    "SPLITLIKE_PRICE_RATIO",
    "HkRiskFlags",
    "classify_hk_risk",
    "describe_hk_risk",
    "is_extreme_daily_move",
    "is_illiquid",
    "is_penny_stock",
    "is_price_discontinuous",
]
