"""Shared style/theme preference matching helpers for screen tool and previews."""

from __future__ import annotations

from typing import Any

STYLE_LABELS = {"trend": "趋势", "pullback": "低吸", "quality": "质量"}


def has_style_preference(value: Any) -> bool:
    return isinstance(value, dict) and bool(value.get("styles") or str(value.get("raw") or "").strip())


def has_theme_preference(value: Any) -> bool:
    return isinstance(value, dict) and bool(value.get("theme") or str(value.get("raw") or "").strip())


def style_preference_styles(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [str(item) for item in value.get("styles") or [] if str(item)][:4]


def style_preference_labels(value: Any) -> list[str]:
    return [STYLE_LABELS.get(item, item) for item in style_preference_styles(value)]


def candidate_matches_preference(row: dict[str, Any], prefix: str) -> bool:
    if row.get(f"{prefix}_match") is True:
        return True
    try:
        if int(row.get(f"{prefix}_match_score") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return bool(row.get(f"{prefix}_match_reasons"))


def preference_match_status(rows: list[dict[str, Any]], prefix: str) -> str:
    return "hit" if any(candidate_matches_preference(row, prefix) for row in rows) else "miss"


def candidate_style_match_styles(row: dict[str, Any], requested: list[str]) -> list[str]:
    styles = [str(item) for item in row.get("style_match_styles") or [] if str(item)]
    if not styles:
        styles = infer_style_match_styles(row)
    if not styles and row.get("style_match") is True:
        styles = requested
    return list(dict.fromkeys(style for style in styles if style in requested))


def infer_style_match_styles(row: dict[str, Any]) -> list[str]:
    reasons = [str(item) for item in row.get("style_match_reasons") or []]
    styles: list[str] = []
    if any(reason.startswith("趋势偏好") for reason in reasons):
        styles.append("trend")
    if any(reason.startswith("低吸偏好") for reason in reasons):
        styles.append("pullback")
    if any(reason.startswith("稳健偏好") for reason in reasons):
        styles.append("quality")
    return styles


def style_preference_match_status(rows: list[dict[str, Any]], preference: Any) -> str:
    if not has_style_preference(preference):
        return ""
    requested = style_preference_styles(preference)
    if not requested:
        return preference_match_status(rows, "style")
    if any(not missing_style_preference_labels(row, preference) for row in rows):
        return "hit"
    if any(candidate_style_match_styles(row, requested) for row in rows):
        return "partial"
    return "miss"


def missing_style_preference_labels(row: dict[str, Any], style_preference: Any) -> list[str]:
    requested = style_preference_styles(style_preference)
    if not requested:
        return []
    matched = set(candidate_style_match_styles(row, requested))
    return [STYLE_LABELS.get(style, style) for style in requested if style not in matched]


def style_preference_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    styles = style_preference_labels(value)
    if styles:
        return ",".join(dict.fromkeys(styles))
    return str(value.get("raw") or "").strip()[:40]


def theme_preference_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("theme") or value.get("raw") or "").strip()[:40]
