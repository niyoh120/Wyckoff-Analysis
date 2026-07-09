"""Market universe file loaders."""

from __future__ import annotations

import json
from pathlib import Path


def load_us_symbols() -> tuple[list[str], dict[str, str]]:
    return _load_market_symbols("us.txt", "us_meta.json")


def load_hk_symbols() -> tuple[list[str], dict[str, str]]:
    return _load_market_symbols("hk.txt", "hk_meta.json")


def _load_market_symbols(symbol_file: str, meta_file: str) -> tuple[list[str], dict[str, str]]:
    base_dir = Path(__file__).resolve().parent.parent / "data" / "market_universes"
    symbols = _load_symbol_lines(base_dir / symbol_file)
    name_map = _load_name_map(base_dir / meta_file)
    if not symbols and name_map:
        symbols = sorted(name_map.keys())
    return symbols, name_map


def _load_symbol_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def _load_name_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return _name_map_from_meta(meta)


def _name_map_from_meta(meta: object) -> dict[str, str]:
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
