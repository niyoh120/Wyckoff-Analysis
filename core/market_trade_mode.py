"""Market-regime trading permission policy."""

from __future__ import annotations

from dataclasses import dataclass

NO_NEW_BUY_REGIMES = frozenset({"RISK_OFF", "CRASH", "BLACK_SWAN"})
REPAIR_REVIEW_REGIMES = frozenset({"BEAR_REBOUND", "PANIC_REPAIR"})
CAUTION_REGIMES = frozenset({"NEUTRAL", "CAUTION"})


@dataclass(frozen=True)
class MarketTradeMode:
    regime: str
    mode: str
    label: str
    action: str
    reason: str
    allow_ai_review: bool
    allow_recommendation_write: bool
    allow_full_l4: bool
    allow_bypass_review: bool
    allow_theme_promotion: bool


def normalize_regime(regime: str | None) -> str:
    return str(regime or "NEUTRAL").strip().upper() or "NEUTRAL"


def resolve_market_trade_mode(regime: str | None) -> MarketTradeMode:
    regime_norm = normalize_regime(regime)
    if regime_norm in NO_NEW_BUY_REGIMES:
        return MarketTradeMode(
            regime=regime_norm,
            mode="observe_only",
            label="禁止新仓",
            action="禁止新仓：仅影子观察，不送AI、不写推荐、不生成新买入",
            reason=f"{regime_norm} 回测全周期弱势，新开仓胜率不足",
            allow_ai_review=False,
            allow_recommendation_write=False,
            allow_full_l4=False,
            allow_bypass_review=False,
            allow_theme_promotion=False,
        )
    if regime_norm in REPAIR_REVIEW_REGIMES:
        return MarketTradeMode(
            regime=regime_norm,
            mode="repair_review",
            label="观察买入",
            action="观察买入：允许少量二次确认候选进入AI复核；不写正式推荐，尾盘人工确认",
            reason=f"{regime_norm} 只适合验证修复强度，禁止自动开仓",
            allow_ai_review=True,
            allow_recommendation_write=False,
            allow_full_l4=False,
            allow_bypass_review=False,
            allow_theme_promotion=False,
        )
    if regime_norm in CAUTION_REGIMES:
        return MarketTradeMode(
            regime=regime_norm,
            mode="confirmation_only",
            label="观察买入",
            action="观察买入：只允许二次确认候选，关闭形态旁路和战略主题送审",
            reason="震荡市优先控制误触发，候选必须经过确认支撑",
            allow_ai_review=True,
            allow_recommendation_write=True,
            allow_full_l4=False,
            allow_bypass_review=False,
            allow_theme_promotion=False,
        )
    return MarketTradeMode(
        regime=regime_norm,
        mode="risk_on",
        label="可执行买入",
        action="可执行买入：允许买点确认、主题加权与强势旁路进入AI复核",
        reason="市场水温支持交易，优先二次确认并允许强势延续",
        allow_ai_review=True,
        allow_recommendation_write=True,
        allow_full_l4=True,
        allow_bypass_review=True,
        allow_theme_promotion=True,
    )
