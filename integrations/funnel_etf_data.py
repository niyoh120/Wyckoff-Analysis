"""ETF universe integration for the funnel."""

from __future__ import annotations

import logging
from pathlib import Path

DEFAULT_ETF_UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "data" / "market_universes" / "etf_cn.txt"
logger = logging.getLogger(__name__)


def load_etf_universe(path: Path = DEFAULT_ETF_UNIVERSE_PATH) -> tuple[list[str], dict[str, str]]:
    if not path.is_file():
        return [], {}
    codes: list[str] = []
    sector_map: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        code, tag = _parse_etf_universe_line(raw)
        if code:
            codes.append(code)
            sector_map[code] = tag
    return codes, sector_map


def _parse_etf_universe_line(raw: str) -> tuple[str, str]:
    line = raw.split("#", 1)[0].strip()
    if not line:
        return "", ""
    parts = line.split(None, 1)
    if len(parts) < 2:
        return "", ""
    code, tag = parts[0].strip(), parts[1].strip()
    return (code, tag) if len(code) == 6 and code.isdigit() and tag else ("", "")
