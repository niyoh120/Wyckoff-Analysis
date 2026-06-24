"""FunnelConfig environment overrides for workflow entrypoints."""

from __future__ import annotations

import logging
import os
from dataclasses import fields as dataclass_fields

from core.wyckoff_engine import FunnelConfig
from utils.env import parse_bool

logger = logging.getLogger(__name__)


def funnel_cfg_overrides_from_env() -> dict[str, object]:
    overrides: dict[str, object] = {}
    for field in dataclass_fields(FunnelConfig):
        if field.name == "enable_evr_trigger":
            continue
        key = f"FUNNEL_CFG_{field.name.upper()}"
        raw = os.getenv(key)
        if raw is None or not raw.strip():
            continue
        parsed = _parse_override_value(FunnelConfig(), field.name, raw)
        if parsed is not None:
            overrides[field.name] = parsed
    return overrides


def apply_funnel_cfg_overrides(cfg: FunnelConfig, overrides: dict[str, object] | None = None) -> None:
    for name, value in (overrides if overrides is not None else funnel_cfg_overrides_from_env()).items():
        if name == "enable_evr_trigger":
            continue
        if hasattr(cfg, name):
            setattr(cfg, name, value)


def _parse_override_value(default_cfg: FunnelConfig, name: str, raw: str) -> object | None:
    try:
        current = getattr(default_cfg, name, None)
        val = raw.strip()
        if isinstance(current, bool):
            return parse_bool(val)
        if isinstance(current, int) and not isinstance(current, bool):
            return int(float(val))
        if isinstance(current, float):
            return float(val)
        return val
    except Exception as exc:
        logger.warning("忽略非法 FunnelConfig 覆盖 FUNNEL_CFG_%s=%r: %s", name.upper(), raw, exc)
        return None
