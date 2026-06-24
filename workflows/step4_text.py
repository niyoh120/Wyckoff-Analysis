"""Small text normalization helpers for Step4 OMS."""

from __future__ import annotations


def clean_text(raw: object) -> str:
    return str(raw or "").strip()


def contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    text_norm = text.lower()
    return any(keyword.lower() in text_norm for keyword in keywords)


def normalize_track(raw: object) -> str:
    text = clean_text(raw)
    text_norm = text.lower()
    if text_norm == "trend":
        return "Trend"
    if text_norm == "accum":
        return "Accum"
    if contains_keyword(text, ("markup", "trend", "主升", "点火", "sos", "突破")):
        return "Trend"
    if contains_keyword(text, ("accum", "spring", "lps", "潜伏", "吸筹", "地量", "护盘")):
        return "Accum"
    return ""


def normalize_stage(raw: object) -> str:
    text = clean_text(raw)
    text_norm = text.lower()
    if "markup" in text_norm:
        return "Markup"
    for stage in ("Accum_A", "Accum_B", "Accum_C"):
        if stage.lower() in text_norm:
            return stage
    return ""
