"""Market-specific funnel configuration."""

from __future__ import annotations

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
        funnel_cfg.sos_pct_min = 8.0
        funnel_cfg.sos_vol_ratio = 3.2
        funnel_cfg.spring_vol_ratio = 1.3
        funnel_cfg.evr_max_rise = 3.0
    elif market == "hk":
        funnel_cfg.sos_pct_min = 7.0
        funnel_cfg.sos_vol_ratio = 3.0
        funnel_cfg.spring_tr_max_range_pct = 25.0
        funnel_cfg.global_entry_max_bias_200 = 25.0
        funnel_cfg.accum_price_from_low_max = 0.40
        funnel_cfg.evr_min_turnover = 0.3
    elif market == "etf":
        funnel_cfg.sos_pct_min = 3.5
        funnel_cfg.sos_vol_ratio = 2.0
        funnel_cfg.spring_vol_ratio = 1.0
        funnel_cfg.evr_min_turnover = 0.3
        funnel_cfg.evr_max_rise = 2.0

    return funnel_cfg
