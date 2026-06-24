"""Market universe file loaders."""

from __future__ import annotations

import json
from pathlib import Path


def load_us_symbols() -> tuple[list[str], dict[str, str]]:
    universe_path = Path(__file__).resolve().parent.parent / "data" / "market_universes" / "us.txt"
    symbols = _load_symbol_lines(universe_path)
    name_map = _load_us_name_map(universe_path.with_name("us_meta.json"))
    if not symbols and name_map:
        symbols = sorted(name_map.keys())
    return symbols, name_map


def _load_symbol_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def _load_us_name_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return _us_name_map_from_meta(meta)


def _us_name_map_from_meta(meta: object) -> dict[str, str]:
    if not isinstance(meta, list):
        return {}
    out: dict[str, str] = {}
    for item in meta:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol", "") or item.get("code", "")).strip()
        if sym:
            out[sym] = str(item.get("name", "")).strip()
    return out
