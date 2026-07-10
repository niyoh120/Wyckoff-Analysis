"""Holding-period time management for A-share books."""

from __future__ import annotations

from dataclasses import dataclass

# 非主线短持：对齐近端回测最优 5 日窗口
DEFAULT_SWING_MAX_HOLD_DAYS = 5
# 主线趋势：允许更长，但需结构仍在
DEFAULT_MAINLINE_MAX_HOLD_DAYS = 15


@dataclass(frozen=True)
class HoldingTimeAction:
    action: str  # HOLD | TIME_EXIT | REVIEW_TRIM
    reason: str
    max_hold_days: int


def holding_time_action(
    hold_trade_days: int,
    *,
    is_mainline: bool = False,
    below_ma20: bool = False,
    theme_dry_down: bool = False,
    swing_max_days: int = DEFAULT_SWING_MAX_HOLD_DAYS,
    mainline_max_days: int = DEFAULT_MAINLINE_MAX_HOLD_DAYS,
) -> HoldingTimeAction:
    """Return time-based holding guidance (not a hard broker order)."""
    days = max(int(hold_trade_days), 0)
    if is_mainline:
        return _mainline_time_action(days, below_ma20, theme_dry_down, mainline_max_days)
    return _swing_time_action(days, swing_max_days)


def _swing_time_action(days: int, swing_max_days: int) -> HoldingTimeAction:
    limit = max(int(swing_max_days), 1)
    if days >= limit:
        return HoldingTimeAction(
            action="TIME_EXIT",
            reason=f"非主线仓持有 {days} 日 ≥ {limit} 日时间窗口，建议时间止盈/换股",
            max_hold_days=limit,
        )
    return HoldingTimeAction(
        action="HOLD",
        reason=f"非主线仓持有 {days}/{limit} 日，时间窗口内可继续观察结构",
        max_hold_days=limit,
    )


def _mainline_time_action(
    days: int,
    below_ma20: bool,
    theme_dry_down: bool,
    mainline_max_days: int,
) -> HoldingTimeAction:
    limit = max(int(mainline_max_days), 1)
    if days >= limit and (below_ma20 or theme_dry_down):
        why = "跌破MA20" if below_ma20 else "主题缩量阴跌"
        return HoldingTimeAction(
            action="REVIEW_TRIM",
            reason=f"主线仓持有 {days} 日 ≥ {limit} 日且出现{why}，建议减仓复核",
            max_hold_days=limit,
        )
    if days >= limit:
        return HoldingTimeAction(
            action="HOLD",
            reason=f"主线仓持有 {days} 日已达 {limit} 日，结构仍在则续持，破MA20或主题转弱再减",
            max_hold_days=limit,
        )
    return HoldingTimeAction(
        action="HOLD",
        reason=f"主线仓持有 {days}/{limit} 日，优先跟踪主题与MA20",
        max_hold_days=limit,
    )


def is_mainline_track(track: str | None, stage: str | None = None, tag: str | None = None) -> bool:
    text = " ".join(str(x or "") for x in (track, stage, tag)).lower()
    keys = ("mainline", "主线", "趋势延续", "主升", "markup", "trend")
    return any(k.lower() in text for k in keys)
