"""Structured metadata helpers for market universe files."""

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

UNIVERSE_DIR = Path(__file__).resolve().parent.parent / "data" / "market_universes"
DIST_UNIVERSE_DIR = Path(sys.prefix) / "share" / "youngcan-wyckoff-analysis" / "market_universes"
META_FILES = {
    "us": "us_meta.json",
    "hk": "hk_meta.json",
    "etf_cn": "etf_cn_meta.json",
}
ALIASES_FILE = "aliases.json"


def _read_meta(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _candidate_universe_dirs() -> list[Path]:
    env_dir = Path(os.getenv("MARKET_UNIVERSE_DIR", "")).expanduser()
    candidates = [env_dir] if str(env_dir) != "." else []
    candidates.extend([UNIVERSE_DIR, Path.cwd() / "data" / "market_universes", DIST_UNIVERSE_DIR])
    out: list[Path] = []
    for path in candidates:
        if path and path not in out:
            out.append(path)
    return out


def _resolve_universe_dir() -> Path:
    for path in _candidate_universe_dirs():
        if any((path / filename).is_file() for filename in META_FILES.values()):
            return path
    return UNIVERSE_DIR


def _code_from_symbol(symbol: str) -> str:
    return str(symbol or "").split(".", 1)[0].strip().upper()


@lru_cache(maxsize=1)
def load_all_market_meta() -> dict[str, list[dict[str, Any]]]:
    """Load all generated market metadata files."""
    base_dir = _resolve_universe_dir()
    aliases = _load_aliases_by_symbol(base_dir)
    return {
        market: _merge_aliases(_read_meta(base_dir / filename), aliases, market)
        for market, filename in META_FILES.items()
    }


def _load_aliases_by_symbol(base_dir: Path) -> dict[str, dict[str, Any]]:
    rows = _read_meta(base_dir / ALIASES_FILE)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol", "") or "").strip().upper()
        if symbol:
            out[symbol] = row
    return out


def _merge_aliases(rows: list[dict[str, Any]], aliases: dict[str, dict[str, Any]], market: str) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        item = dict(row)
        symbol = str(item.get("symbol", "") or "").strip().upper()
        alias = aliases.get(symbol, {})
        if alias:
            item["name"] = str(item.get("name") or alias.get("name") or symbol)
            item["aliases"] = alias.get("aliases", [])
        merged.append(item)
        if symbol:
            seen.add(symbol)
    for symbol, alias in aliases.items():
        if symbol not in seen and str(alias.get("market", "") or "").lower() == market:
            item = dict(alias)
            item.setdefault("code", _code_from_symbol(symbol))
            merged.append(item)
    return merged


def load_market_meta(markets: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Load metadata entries for selected markets."""
    all_meta = load_all_market_meta()
    selected = markets or tuple(all_meta.keys())
    rows: list[dict[str, Any]] = []
    for market in selected:
        rows.extend(all_meta.get(market, []))
    return rows


def load_symbol_name_map(markets: tuple[str, ...] = ()) -> dict[str, str]:
    """Return code/symbol to display-name map where metadata has a name."""
    out: dict[str, str] = {}
    for row in load_market_meta(markets):
        name = str(row.get("name", "") or "").strip()
        if not name:
            continue
        symbol = str(row.get("symbol", "") or "").strip().upper()
        code = str(row.get("code", "") or "").strip().upper()
        if symbol:
            out[symbol] = name
        if code:
            out[code] = name
    return out


def _etf_name_map_from_txt() -> dict[str, str]:
    path = UNIVERSE_DIR / "etf_cn.txt"
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("#", 1)[0].strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 6 and parts[0].isdigit():
            result[parts[0]] = f"{parts[1]}ETF"
    return result


def load_etf_name_map() -> dict[str, str]:
    """Return ETF code to display-name map, preferring structured meta over the plain-text fallback."""
    meta_map = load_symbol_name_map(("etf_cn",))
    out = {code: name for code, name in meta_map.items() if len(code) == 6 and code.isdigit()}
    return out or _etf_name_map_from_txt()


def search_market_meta(query: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Search generated market metadata by symbol, code, or name."""
    q = str(query or "").strip().upper()
    if not q:
        return []
    matches: list[tuple[int, dict[str, Any]]] = []
    for row in load_market_meta():
        score = _match_score(row, q)
        if score is not None:
            matches.append((score, row))
    matches.sort(key=lambda item: (item[0], str(item[1].get("symbol", ""))))
    return [row for _, row in matches[: max(limit, 0)]]


def _match_score(row: dict[str, Any], query: str) -> int | None:
    fields = [str(row.get(key, "") or "").upper() for key in ("symbol", "code", "name", "sector_tag")]
    aliases = row.get("aliases")
    if isinstance(aliases, list):
        fields.extend(str(item or "").upper() for item in aliases)
    if query in fields:
        return 0
    if any(field.startswith(query) for field in fields if field):
        return 1
    haystack = " ".join(fields)
    if query in haystack:
        return 2
    return None
