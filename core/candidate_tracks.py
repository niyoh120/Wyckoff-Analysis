"""Candidate track normalization shared by selection paths."""

from __future__ import annotations

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

    key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in ACCUM_TRACK_KEYS:
        return "Accum"
    if key in TREND_TRACK_KEYS:
        return "Trend"
    return "Accum" if default == "Accum" else "Trend"
