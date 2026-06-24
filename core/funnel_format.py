"""Shared compact formatting helpers for funnel reports."""

from __future__ import annotations


def fmt_pct(value: object) -> str:
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "-"


def fmt_ratio(value: object) -> str:
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return "-"
