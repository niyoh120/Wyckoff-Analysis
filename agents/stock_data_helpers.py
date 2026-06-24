from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_NAME_MAP: dict[str, str] | None = None


def code_to_name(code: str) -> str:
    global _NAME_MAP
    if _NAME_MAP is None:
        _NAME_MAP = _load_name_map()
    return _NAME_MAP.get(code, code)


def collect_tickflow_limit_hints_from_df(df: Any) -> list[str]:
    if df is None or not hasattr(df, "attrs"):
        return []
    attrs = getattr(df, "attrs", {}) or {}
    hints = attrs.get("tickflow_limit_hints")
    if isinstance(hints, list):
        return _dedupe_texts(hints)
    one = str(attrs.get("tickflow_limit_hint", "") or "").strip()
    return [one] if one else []


def hist_metadata(df: Any) -> dict[str, Any]:
    if df is None or not hasattr(df, "attrs"):
        return {}
    attrs = getattr(df, "attrs", {}) or {}
    meta: dict[str, Any] = {}
    for key in ("source", "upstream_source", "cache_status", "cached_until"):
        val = str(attrs.get(key, "") or "").strip()
        if val:
            meta[key] = val
    _copy_upstream_sources(attrs, meta)
    with suppress(Exception):
        meta["row_count"] = int(len(df))
    return meta


def latest_hist_date(df: Any, date_col: str = "date") -> str:
    if df is None or not hasattr(df, "empty") or df.empty:
        return ""
    try:
        return str(df.iloc[-1].get(date_col, "") or "")
    except Exception:
        return ""


def _load_name_map() -> dict[str, str]:
    try:
        from integrations.fetch_a_share_csv import get_all_stocks

        name_map = {s["code"]: s["name"] for s in get_all_stocks()}
    except Exception:
        name_map = {}
    name_map.update(_load_etf_name_map())
    return name_map


def _load_etf_name_map() -> dict[str, str]:
    try:
        from tools.market_universe_meta import load_symbol_name_map

        meta_map = load_symbol_name_map(("etf_cn",))
        out = {code: name for code, name in meta_map.items() if len(code) == 6 and code.isdigit()}
        if out:
            return out
    except Exception:
        logger.debug("failed to load ETF name map from symbol metadata", exc_info=True)
    return _load_etf_name_map_from_file()


def _load_etf_name_map_from_file() -> dict[str, str]:
    path = Path(__file__).resolve().parent.parent / "data" / "market_universes" / "etf_cn.txt"
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("#", 1)[0].strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 6 and parts[0].isdigit():
            result[parts[0]] = f"{parts[1]}ETF"
    return result


def _dedupe_texts(items: list[Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _copy_upstream_sources(attrs: dict[str, Any], meta: dict[str, Any]) -> None:
    upstream_sources = attrs.get("upstream_sources")
    if isinstance(upstream_sources, list):
        clean = [str(x) for x in upstream_sources if str(x or "").strip()]
        if clean:
            meta["upstream_sources"] = clean
