"""Candidate track normalization shared by selection paths."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

ACCUM_TRACK_KEYS = {
    "accum",
    "accumulation",
    "accumulation_ready",
    "compression",
    "lps",
    "spring",
}

TREND_TRACK_KEYS = {
    "breakout",
    "evr",
    "future_leader",
    "mainline",
    "sos",
    "trend",
    "trend_breakout",
    "trend_lane_pullback",
    "trend_pullback",
}


def normalize_candidate_track(raw: Any, *, default: str = "Trend") -> str:
    """Return canonical Trend/Accum for candidate entry track values."""

    key = normalize_candidate_entry_key(raw)
    if key in ACCUM_TRACK_KEYS:
        return "Accum"
    if key in TREND_TRACK_KEYS:
        return "Trend"
    return "Accum" if default == "Accum" else "Trend"


def normalize_candidate_entry_key(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    key = re.sub(r"[\s-]+", "_", key)
    return re.sub(r"_+", "_", key).strip("_")


def candidate_entry_key(
    item: Mapping[str, Any],
    known_keys: Iterable[str] | None = None,
    *,
    fields: tuple[str, ...] = ("entry_type", "signal_key", "lane"),
) -> str:
    known = {normalize_candidate_entry_key(key) for key in known_keys or []}
    fallback = ""
    for field in fields:
        key = normalize_candidate_entry_key(item.get(field))
        if not key:
            continue
        fallback = fallback or key
        if not known or key in known:
            return key
    return fallback
