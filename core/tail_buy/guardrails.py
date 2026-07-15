from __future__ import annotations

from typing import Any

from core.tail_buy.models import TailBuyCandidate, normalize_regime, safe_float

# 硬防守：任何信号都不放行新开仓。
# PANIC_REPAIR_CONFIRMED/INTRADAY 不在此列——它们走 decision_semantics 的 PROBE_READY 路径（5% 仓位限额）。
HARD_BLOCK_REGIMES = frozenset(
    {
        "UNKNOWN",
        "RISK_OFF",
        "BLACK_SWAN",
        "BEAR_REBOUND",
        "PANIC_REPAIR",
        "CRASH_INTRADAY",
    }
)

# 分层放行：regime → 允许新开仓的信号类型小写集合。
# 数据来源：signal_registry 按 signal_type x regime 的真实胜率/均值。
TIERED_ALLOW_SIGNALS: dict[str, frozenset[str]] = {
    # CRASH: EVR 70.6%胜率+2.19%均值, launchpad 45.2%+1.99%, trend_breakout 47.0%+1.80%(已退役但仍统计)
    "CRASH": frozenset({"evr", "launchpad"}),
    # RISK_ON: launchpad 67.2%+6.61%, trend_lane_pullback 51.4%+0.32%
    # SOS/EVR 在 RISK_ON 下反而表现差(26.9%/33.3%)，不放行
    "RISK_ON": frozenset({"launchpad", "trend_lane_pullback"}),
}

DEFENSIVE_TAIL_REGIMES = {
    "RISK_OFF",
    "PANIC_REPAIR",
    "PANIC_REPAIR_CONFIRMED",
    "CRASH",
    "BLACK_SWAN",
    "CRASH_INTRADAY",
}
REPAIR_TAIL_REGIMES = {"PANIC_REPAIR_INTRADAY", "PANIC_REPAIR_CONFIRMED"}
NAKED_MOMENTUM_SIGNALS = {"sos", "evr"}


def tail_hard_veto_reasons(features: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    support = safe_float(features.get("support_level"), 0.0)
    if support > 0 and bool(features.get("day_low_breached_support")):
        reasons.append(f"当天跌破确认支撑{support:.2f}，尾盘不买")
    elif support > 0 and bool(features.get("close_below_support")):
        reasons.append(f"尾盘收在确认支撑{support:.2f}下方")
    if bool(features.get("tail_blowoff_reversal")):
        reasons.append("极端放量冲高回落，疑似派发")
    return reasons


def tail_entry_veto_reasons(features: dict[str, Any], signal_type: str, market_regime: str) -> list[str]:
    reasons: list[str] = []
    st_lower = str(signal_type or "").strip().lower()
    support = safe_float(features.get("support_level"), 0.0)
    regime = normalize_regime(market_regime or features.get("market_regime"))
    if st_lower != "holding" and regime in HARD_BLOCK_REGIMES:
        reasons.append(f"{regime}禁止新开仓，尾盘不买")
    elif st_lower != "holding":
        allowed = TIERED_ALLOW_SIGNALS.get(regime)
        if allowed is not None and st_lower not in allowed:
            reasons.append(f"{regime}仅放行{','.join(sorted(allowed))}，{st_lower}尾盘不买")
    if st_lower != "holding" and support <= 0:
        reasons.append("缺少确认支撑位，尾盘不买")
    if st_lower == "evr" and regime in DEFENSIVE_TAIL_REGIMES and regime not in TIERED_ALLOW_SIGNALS:
        reasons.append(f"{regime}单EVR只观察，尾盘不买")
    if st_lower in NAKED_MOMENTUM_SIGNALS and regime in REPAIR_TAIL_REGIMES:
        reasons.append(f"{regime}单{st_lower.upper()}只观察，尾盘不买")
    return reasons


def tail_candidate_veto_reasons(item: TailBuyCandidate) -> list[str]:
    reasons = tail_hard_veto_reasons(item.features)
    if item.features:
        reasons.extend(tail_entry_veto_reasons(item.features, item.signal_type, item.market_regime))
    return reasons
