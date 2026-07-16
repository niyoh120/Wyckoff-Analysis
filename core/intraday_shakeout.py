"""日内路径分类（纯计算层）：区分"洗盘"与"出货/确认破位"。

日线收盘价相同的两根大跌 K 线，可能对应完全不同的盘中路径：
- 开盘跳水直接砸出支撑、尾盘弱势收报 → 出货/确认破位
- 盘中一度跌破支撑但快速拉回、尾盘收在日内高位区 → 洗盘/Spring 式挤压

本模块提供不依赖任何盘中买入信号上下文的通用分类器，
供持仓诊断、Wyckoff Spring 判断等场景复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from core.intraday_analysis import (
    compute_effort_vs_result,
    compute_vol_price_corr,
    ensure_intraday_df,
)

PATH_WASHOUT = "washout"  # 疑似洗盘：跌破支撑但收盘收回，未确认破位
PATH_DISTRIBUTION = "distribution"  # 疑似出货：放量下跌且尾盘走弱，确认破位特征
PATH_STRONG = "strong"  # 全天强势，跌破无效或未曾跌破
PATH_NEUTRAL = "neutral"  # 结构中性，无法归入以上任一类
PATH_INSUFFICIENT_DATA = "insufficient_data"  # 分钟线不足，无法判断

_CLOSE_POS_STRONG = 0.62
_CLOSE_POS_WEAK = 0.38
_TAIL_VOLUME_SHARE_MAX = 0.55  # 尾段放量占比超过此值，视为尾盘抛压过重
_SUPPORT_BREACH_TOLERANCE_PCT = 0.3


@dataclass
class IntradayPathResult:
    path_type: str
    reasons: list[str] = field(default_factory=list)
    support_level: float = 0.0
    day_low: float = 0.0
    close_pos: float = 0.0
    day_low_breached_support: bool = False
    close_below_support: bool = False
    tail_volume_share: float = 0.0
    effort_vs_result: float = 0.0
    vol_price_corr: float = 0.0
    bars: int = 0

    def to_dict(self) -> dict:
        return {
            "path_type": self.path_type,
            "reasons": list(self.reasons),
            "support_level": self.support_level,
            "day_low": self.day_low,
            "close_pos": round(self.close_pos, 3),
            "day_low_breached_support": self.day_low_breached_support,
            "close_below_support": self.close_below_support,
            "tail_volume_share": round(self.tail_volume_share, 3),
            "effort_vs_result": self.effort_vs_result,
            "vol_price_corr": self.vol_price_corr,
            "bars": self.bars,
        }


def _insufficient(bars: int) -> IntradayPathResult:
    return IntradayPathResult(path_type=PATH_INSUFFICIENT_DATA, reasons=["分时数据不足，无法判断日内路径"], bars=bars)


def _resolve_support(df: pd.DataFrame, support_level: float | None) -> float:
    if support_level and support_level > 0:
        return float(support_level)
    # 无外部支撑位时，用当日开盘前 60% 区间的最低点近似估计盘中支撑参照。
    n = len(df)
    if n < 20:
        return 0.0
    split = int(n * 0.6)
    low = pd.to_numeric(df["low"], errors="coerce").fillna(df["close"])
    return float(low.iloc[:split].min())


def _support_breach_features(df: pd.DataFrame, support: float) -> dict[str, float | bool]:
    if support <= 0:
        return {"day_low_breached_support": False, "close_below_support": False}
    close = pd.to_numeric(df["close"], errors="coerce").ffill()
    low = pd.to_numeric(df["low"], errors="coerce").fillna(close)
    floor = support * (1.0 - _SUPPORT_BREACH_TOLERANCE_PCT / 100.0)
    return {
        "day_low_breached_support": bool(float(low.min()) < floor),
        "close_below_support": bool(float(close.iloc[-1]) < floor),
    }


def _tail_volume_share(volume: pd.Series, lookback: int = 30) -> float:
    total = float(volume.sum())
    if total <= 0:
        return 0.0
    return float(volume.tail(min(lookback, len(volume))).sum()) / total


def _base_path_features(df: pd.DataFrame, support_level: float | None) -> dict:
    close = pd.to_numeric(df["close"], errors="coerce").ffill()
    high = pd.to_numeric(df["high"], errors="coerce").fillna(close)
    low = pd.to_numeric(df["low"], errors="coerce").fillna(close)
    volume = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    day_high = float(high.max())
    day_low = float(low.min())
    day_range = max(day_high - day_low, 1e-8)
    close_pos = max(0.0, min(1.0, (float(close.iloc[-1]) - day_low) / day_range))
    support = _resolve_support(df, support_level)
    breach = _support_breach_features(df, support)
    return {
        "close_pos": close_pos,
        "day_low": day_low,
        "support_level": support,
        "tail_volume_share": _tail_volume_share(volume),
        "effort_vs_result": compute_effort_vs_result(df),
        "vol_price_corr": compute_vol_price_corr(df),
        **breach,
    }


def _classify_from_features(feat: dict, *, day_change_pct: float | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    breached = bool(feat["day_low_breached_support"])
    closed_below = bool(feat["close_below_support"])
    close_pos = float(feat["close_pos"])
    tail_share = float(feat["tail_volume_share"])
    evr = float(feat["effort_vs_result"])

    if closed_below:
        reasons.append("收盘仍在支撑下方，未收复失地")
        if tail_share >= _TAIL_VOLUME_SHARE_MAX:
            reasons.append(f"尾段放量占比过高({tail_share:.0%})，抛压集中在尾盘")
        return PATH_DISTRIBUTION, reasons

    if breached and close_pos >= _CLOSE_POS_STRONG:
        reasons.append("盘中跌破支撑但收盘收回至日内高位区")
        if evr > 10:
            reasons.append("放量但价格未进一步走弱，符合承接/洗盘特征")
        return PATH_WASHOUT, reasons

    if breached and close_pos < _CLOSE_POS_WEAK:
        reasons.append("跌破支撑后收盘仍在日内低位区，未见有效收复")
        return PATH_DISTRIBUTION, reasons

    if not breached and close_pos >= _CLOSE_POS_STRONG:
        reasons.append("全天未有效跌破支撑，收盘位置偏强")
        return PATH_STRONG, reasons

    if day_change_pct is not None and day_change_pct <= -5.0 and close_pos < _CLOSE_POS_WEAK:
        reasons.append(f"当日跌幅{day_change_pct:.1f}%且收盘位置偏低，倾向确认走弱")
        return PATH_DISTRIBUTION, reasons

    reasons.append("未出现明确的洗盘收复或破位确认特征")
    return PATH_NEUTRAL, reasons


def classify_intraday_path(
    df_1m: pd.DataFrame,
    *,
    support_level: float | None = None,
    day_change_pct: float | None = None,
    min_bars: int = 60,
) -> IntradayPathResult:
    """基于当日分钟线判断日内路径类型：洗盘 / 出货 / 强势 / 中性 / 数据不足。

    Parameters
    ----------
    df_1m : 当日 1 分钟 K 线（含 open/high/low/close/volume）
    support_level : 外部传入的关键支撑位（如前期低点、MA20）；缺省时用日内前 60% 区间低点近似
    day_change_pct : 当日涨跌幅（%），用于辅助判断"跌幅很大但无法从盘口确认路径"的兜底场景
    min_bars : 最少所需分钟线根数，默认 60（约 1 小时）
    """
    df = ensure_intraday_df(df_1m)
    if df.empty or len(df) < min_bars:
        return _insufficient(len(df))

    feat = _base_path_features(df, support_level)
    path_type, reasons = _classify_from_features(feat, day_change_pct=day_change_pct)
    return IntradayPathResult(
        path_type=path_type,
        reasons=reasons,
        support_level=feat["support_level"],
        day_low=feat["day_low"],
        close_pos=feat["close_pos"],
        day_low_breached_support=feat["day_low_breached_support"],
        close_below_support=feat["close_below_support"],
        tail_volume_share=feat["tail_volume_share"],
        effort_vs_result=feat["effort_vs_result"],
        vol_price_corr=feat["vol_price_corr"],
        bars=len(df),
    )


PATH_LABELS = {
    PATH_WASHOUT: "洗盘/挤压式回踩",
    PATH_DISTRIBUTION: "出货/确认破位",
    PATH_STRONG: "全天强势",
    PATH_NEUTRAL: "结构中性",
    PATH_INSUFFICIENT_DATA: "数据不足",
}


def describe_intraday_path(result: IntradayPathResult) -> str:
    label = PATH_LABELS.get(result.path_type, result.path_type)
    if result.path_type == PATH_INSUFFICIENT_DATA:
        return label
    reason = result.reasons[0] if result.reasons else ""
    return f"{label}：{reason}" if reason else label


__all__ = [
    "PATH_DISTRIBUTION",
    "PATH_INSUFFICIENT_DATA",
    "PATH_LABELS",
    "PATH_NEUTRAL",
    "PATH_STRONG",
    "PATH_WASHOUT",
    "IntradayPathResult",
    "classify_intraday_path",
    "describe_intraday_path",
]
