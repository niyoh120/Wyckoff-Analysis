"""External candidate seed config and observation helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from integrations.fetch_a_share_csv import normalize_symbols
from utils.env import parse_bool

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = ROOT / "config" / "profiles" / "a_share_prod.yml"


@dataclass(frozen=True)
class ExternalSeedConfig:
    enabled: bool = False
    source: str = "external"
    symbols: tuple[str, ...] = ()
    symbols_file: str = ""
    max_symbols: int = 30
    allow_l2_bypass_review: bool = True
    watch_ttl_days: int = 10
    retention_days: int = 180


def _int_value(raw: Any, default: int, *, minimum: int = 0) -> int:
    try:
        return max(int(float(raw)), minimum)
    except (TypeError, ValueError):
        return default


def _bool_value(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return parse_bool(str(raw))


def _profile_path() -> Path:
    raw_path = os.getenv("WYCKOFF_CONFIG_PATH", "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    profile = os.getenv("WYCKOFF_CONFIG_PROFILE", "a_share_prod").strip() or "a_share_prod"
    if "/" in profile or profile.endswith((".yml", ".yaml")):
        return Path(profile).expanduser()
    return ROOT / "config" / "profiles" / f"{profile}.yml"


def _load_profile_section() -> dict[str, Any]:
    path = _profile_path()
    if not path.exists() and path == DEFAULT_PROFILE:
        return {}
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = data.get("external_seeds") if isinstance(data, dict) else {}
    return section if isinstance(section, dict) else {}


def _split_symbols(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list | tuple):
        return [str(x.get("code") or x.get("symbol") or x) if isinstance(x, dict) else str(x) for x in raw]
    text = str(raw).replace(";", ",").replace("\n", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def _file_symbols(path_raw: str) -> list[str]:
    if not path_raw:
        return []
    path = Path(path_raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return _json_symbols(json.loads(text))
    return _split_symbols(text)


def _json_symbols(data: Any) -> list[str]:
    if isinstance(data, dict):
        for key in ("symbols", "candidates", "codes"):
            if key in data:
                return _split_symbols(data[key])
        return []
    return _split_symbols(data)


def _env_value(*names: str) -> str | None:
    for name in names:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _configured_symbols(section: dict[str, Any]) -> tuple[list[str], bool]:
    env_symbols = _env_value("FUNNEL_EXTERNAL_SEED_SYMBOLS", "FUNNEL_EXTRA_SYMBOLS")
    symbols = _split_symbols(section.get("symbols"))
    symbols.extend(_file_symbols(str(section.get("symbols_file") or "")))
    if env_symbols:
        symbols.extend(_split_symbols(env_symbols))
    return normalize_symbols(symbols), bool(env_symbols)


def load_external_seed_config() -> ExternalSeedConfig:
    section = _load_profile_section()
    symbols, env_symbols_present = _configured_symbols(section)
    max_symbols = _int_value(_env_value("FUNNEL_EXTERNAL_SEED_MAX") or section.get("max_symbols"), 30, minimum=1)
    enabled_raw = _env_value("FUNNEL_EXTERNAL_SEEDS_ENABLED")
    enabled = _bool_value(enabled_raw, _bool_value(section.get("enabled"), False))
    if enabled_raw is None and env_symbols_present:
        enabled = True
    symbols = symbols[:max_symbols]
    return ExternalSeedConfig(
        enabled=enabled and bool(symbols),
        source=_env_value("FUNNEL_EXTERNAL_SEED_SOURCE") or str(section.get("source") or "external"),
        symbols=tuple(symbols),
        symbols_file=str(section.get("symbols_file") or ""),
        max_symbols=max_symbols,
        allow_l2_bypass_review=_bool_value(
            _env_value("FUNNEL_EXTERNAL_SEED_L2_BYPASS") or section.get("allow_l2_bypass_review"),
            True,
        ),
        watch_ttl_days=_int_value(
            _env_value("FUNNEL_EXTERNAL_SEED_WATCH_TTL_DAYS") or section.get("watch_ttl_days"),
            10,
            minimum=1,
        ),
        retention_days=_int_value(
            _env_value("FUNNEL_EXTERNAL_SEED_RETENTION_DAYS") or section.get("retention_days"),
            180,
            minimum=30,
        ),
    )


def append_external_symbols(symbols: list[str], cfg: ExternalSeedConfig) -> tuple[list[str], int]:
    if not cfg.enabled:
        return symbols, 0
    seen = set(symbols)
    merged = list(symbols)
    for code in cfg.symbols:
        if code not in seen:
            merged.append(code)
            seen.add(code)
    return merged, len(merged) - len(symbols)


def trigger_tags_by_code(triggers: dict[str, list[tuple[str, float]]]) -> dict[str, list[str]]:
    tags: dict[str, set[str]] = {}
    for signal_type, hits in (triggers or {}).items():
        for code, _score in hits or []:
            code_s = str(code).strip()
            if code_s:
                tags.setdefault(code_s, set()).add(str(signal_type).strip().lower())
    return {code: sorted(values) for code, values in tags.items()}


def build_external_seed_rows(
    cfg: ExternalSeedConfig,
    trade_date: str,
    *,
    l1_codes: list[str],
    l2_codes: list[str],
    l4_triggers: dict[str, list[tuple[str, float]]],
    name_map: dict[str, str],
    sector_map: dict[str, str],
) -> list[dict[str, Any]]:
    l1_set = set(l1_codes)
    l2_set = set(l2_codes)
    trigger_tags = trigger_tags_by_code(l4_triggers)
    expires_at = (date.fromisoformat(trade_date) + timedelta(days=cfg.watch_ttl_days)).isoformat()
    return [
        _external_seed_row(cfg, trade_date, code, idx, l1_set, l2_set, trigger_tags, expires_at, name_map, sector_map)
        for idx, code in enumerate(cfg.symbols, start=1)
    ]


def _external_seed_row(
    cfg: ExternalSeedConfig,
    trade_date: str,
    code: str,
    rank: int,
    l1_set: set[str],
    l2_set: set[str],
    trigger_tags: dict[str, list[str]],
    expires_at: str,
    name_map: dict[str, str],
    sector_map: dict[str, str],
) -> dict[str, Any]:
    status = _watch_status(code, l1_set, l2_set, trigger_tags)
    return {
        "market": "cn",
        "trade_date": trade_date,
        "source": cfg.source,
        "source_rank": rank,
        "code": code,
        "name": name_map.get(code, code),
        "industry": sector_map.get(code, ""),
        "passed_l1": code in l1_set,
        "passed_l2": code in l2_set,
        "l4_confirmed": bool(trigger_tags.get(code)),
        "l4_trigger_tags": trigger_tags.get(code, []),
        "watch_status": status,
        "expires_at": expires_at,
        "raw_payload": {
            "allow_l2_bypass_review": cfg.allow_l2_bypass_review,
            "watch_ttl_days": cfg.watch_ttl_days,
        },
    }


def _watch_status(code: str, l1_set: set[str], l2_set: set[str], trigger_tags: dict[str, list[str]]) -> str:
    if code not in l1_set:
        return "REJECTED_L1"
    if code in l2_set:
        return "PASSED_L2"
    if trigger_tags.get(code):
        return "L4_CONFIRMED"
    return "WATCH"
