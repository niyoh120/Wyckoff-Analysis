from core.wyckoff_engine import FunnelConfig
from tools.market_regime import _apply_trigger_threshold_profile


def test_regime_trigger_profile_is_opt_in() -> None:
    cfg = FunnelConfig(regime_trigger_profiles_enabled=False)
    original = (cfg.sos_vol_ratio, cfg.spring_vol_ratio, cfg.evr_vol_ratio)

    _apply_trigger_threshold_profile(cfg, "RISK_ON")

    assert (cfg.sos_vol_ratio, cfg.spring_vol_ratio, cfg.evr_vol_ratio) == original


def test_regime_trigger_profile_scales_volume_thresholds() -> None:
    cfg = FunnelConfig(regime_trigger_profiles_enabled=True)

    _apply_trigger_threshold_profile(cfg, "RISK_OFF")

    assert cfg.sos_vol_ratio == 3.0 * cfg.regime_defensive_volume_multiplier
    assert cfg.spring_vol_ratio == 1.3 * cfg.regime_defensive_volume_multiplier
    assert cfg.evr_vol_ratio == 1.8 * cfg.regime_defensive_volume_multiplier
