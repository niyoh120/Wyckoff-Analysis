"""Load mainline engine config from profile and environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from core.mainline_engine import MainlineEngineConfig
from core.theme_radar import normalize_theme_name
from integrations.fetch_a_share_csv import normalize_symbols
from utils.env import parse_bool

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = ROOT / "config" / "profiles" / "a_share_prod.yml"


def load_mainline_engine_config() -> MainlineEngineConfig:
    section = _load_section()
    return MainlineEngineConfig(
        enabled=_bool_value(_env_value("FUNNEL_MAINLINE_ENGINE_ENABLED") or section.get("enabled"), True),
        max_ai_candidates=_int_value(
            _env_value("FUNNEL_MAINLINE_MAX_AI_CANDIDATES") or section.get("max_ai_candidates"), 3
        ),
        min_theme_score=_float_value(
            _env_value("FUNNEL_MAINLINE_MIN_THEME_SCORE") or section.get("min_theme_score"), 0.55
        ),
        min_stock_score=_float_value(
            _env_value("FUNNEL_MAINLINE_MIN_STOCK_SCORE") or section.get("min_stock_score"), 0.60
        ),
        min_timing_score=_float_value(
            _env_value("FUNNEL_MAINLINE_MIN_TIMING_SCORE") or section.get("min_timing_score"), 0.55
        ),
        allow_l2_bypass=_bool_value(
            _env_value("FUNNEL_MAINLINE_ALLOW_L2_BYPASS") or section.get("allow_l2_bypass"), True
        ),
        allow_l4_bypass=_bool_value(
            _env_value("FUNNEL_MAINLINE_ALLOW_L4_BYPASS") or section.get("allow_l4_bypass"), False
        ),
        max_candidates_per_theme=_int_value(section.get("max_candidates_per_theme"), 8),
        themes=_themes(section.get("themes")),
        core_basket=_core_basket(section.get("core_basket")),
    )


def _profile_path() -> Path:
    raw_path = os.getenv("WYCKOFF_CONFIG_PATH", "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    profile = os.getenv("WYCKOFF_CONFIG_PROFILE", "a_share_prod").strip() or "a_share_prod"
    if "/" in profile or profile.endswith((".yml", ".yaml")):
        return Path(profile).expanduser()
    return ROOT / "config" / "profiles" / f"{profile}.yml"


def _load_section() -> dict[str, Any]:
    path = _profile_path()
    if not path.exists() and path == DEFAULT_PROFILE:
        return {}
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = data.get("mainline_engine") if isinstance(data, dict) else {}
    return section if isinstance(section, dict) else {}


def _themes(raw: Any) -> tuple[str, ...]:
    items = raw if isinstance(raw, list | tuple) else []
    out = [normalize_theme_name(str(item)) for item in items]
    return tuple(dict.fromkeys(theme for theme in out if theme))


def _core_basket(raw: Any) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(raw, list | tuple):
        return ()
    rows: list[tuple[str, str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            codes = normalize_symbols([str(item.get("code") or item.get("symbol") or "")])
            theme = normalize_theme_name(str(item.get("theme") or ""))
            name = str(item.get("name") or (codes[0] if codes else "")).strip()
            if codes and theme:
                rows.append((codes[0], name, theme))
    return tuple(rows)


def _env_value(name: str) -> str | None:
    raw = os.getenv(name)
    return str(raw).strip() if raw is not None and str(raw).strip() else None


def _bool_value(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return parse_bool(str(raw))


def _int_value(raw: Any, default: int, *, minimum: int = 0) -> int:
    try:
        return max(int(float(raw)), minimum)
    except (TypeError, ValueError):
        return default


def _float_value(raw: Any, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(float(raw), minimum)
    except (TypeError, ValueError):
        return default
