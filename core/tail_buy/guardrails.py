from __future__ import annotations

from typing import Any

from core.tail_buy.models import TailBuyCandidate, normalize_regime, safe_float

DEFENSIVE_TAIL_REGIMES = {"RISK_OFF", "PANIC_REPAIR", "CRASH", "BLACK_SWAN", "CRASH_INTRADAY"}
REPAIR_TAIL_REGIMES = {"PANIC_REPAIR_INTRADAY"}
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
    if st_lower != "holding" and support <= 0:
        reasons.append("缺少确认支撑位，尾盘不买")
    if st_lower == "evr" and regime in DEFENSIVE_TAIL_REGIMES:
        reasons.append(f"{regime}单EVR只观察，尾盘不买")
    if st_lower in NAKED_MOMENTUM_SIGNALS and regime in REPAIR_TAIL_REGIMES:
        reasons.append(f"{regime}单{st_lower.upper()}只观察，尾盘不买")
    return reasons


def tail_candidate_veto_reasons(item: TailBuyCandidate) -> list[str]:
    reasons = tail_hard_veto_reasons(item.features)
    if item.features:
        reasons.extend(tail_entry_veto_reasons(item.features, item.signal_type, item.market_regime))
    return reasons
