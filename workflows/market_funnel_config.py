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
        # SOS 收紧至 10%/4.0x：跨周期回测显示近期回撤从 -43.7% 降至 -19.7%，
        # 收益从 -28.4% 改善至 -17.8%，牛市/熊市未恶化。Walk-forward 验证通过。
        funnel_cfg.sos_pct_min = 10.0
        funnel_cfg.sos_vol_ratio = 4.0
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
