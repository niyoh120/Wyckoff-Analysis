"""Market-specific funnel configuration."""

from __future__ import annotations

from core.hk_boards import apply_hk_funnel_cfg
from core.wyckoff_engine import FunnelConfig


def funnel_config_for_market(market: str, *, trading_days: int = 320, min_avg_amount: float = 0.0) -> FunnelConfig:
    funnel_cfg = FunnelConfig(trading_days=trading_days)
    funnel_cfg.require_cn_main_or_chinext = False
    funnel_cfg.min_market_cap_yi = 0.0
    funnel_cfg.min_avg_amount_wan = min_avg_amount / 10000.0
    funnel_cfg.enable_rs_filter = True
    funnel_cfg.enable_rs_divergence_channel = True
    funnel_cfg.require_bench_latest_alignment = False

    if market == "us":
        # 恢复收敛前参数：SOS 8%/3.2x，不设低价股闸门（min_avg_amount_wan/RS 过滤
        # 已提供基础流动性把关），全市场含仙股/低价股均纳入候选池观察。
        funnel_cfg.sos_pct_min = 8.0
        funnel_cfg.sos_vol_ratio = 3.2
        funnel_cfg.spring_vol_ratio = 1.3
        funnel_cfg.evr_max_rise = 3.0
    elif market == "hk":
        apply_hk_funnel_cfg(funnel_cfg, min_avg_amount=min_avg_amount)
    elif market == "etf":
        funnel_cfg.sos_pct_min = 3.5
        funnel_cfg.sos_vol_ratio = 2.0
        funnel_cfg.spring_vol_ratio = 1.0
        funnel_cfg.evr_min_turnover = 0.3
        funnel_cfg.evr_max_rise = 2.0

    return funnel_cfg
