"""Shared helpers used by multiple workflow modules."""

from __future__ import annotations

import json
import re
from typing import Any

# ── Marker tuples (duplicated between model_router.py and planner.py) ──

PORTFOLIO_REVIEW_SUBJECT_MARKERS = ("持仓", "仓位", "组合")
PORTFOLIO_REVIEW_STRONG_MARKERS = ("复盘", "体检", "诊断", "总结", "去留", "攻防", "策略")
PORTFOLIO_REVIEW_CONTEXT_MARKERS = ("大盘", "市场", "水温", "盘面", "环境", "今天", "明天", "风险", "建议")

STOCK_STYLE_MARKERS = ("强势", "趋势", "低吸", "右侧", "左侧", "稳健")
STOCK_STYLE_TARGETS = ("票", "标的", "候选")

# ── Text helpers ──


def compact_text(value: Any) -> str:
    """Strip punctuation / whitespace for keyword-matching on user input."""
    return re.sub(r"[\s。！!,.，、？?]+", "", str(value or "").lower())


def collect_stream_text(chunks: Any) -> str:
    """Concatenate text_delta chunks from a streaming provider response."""
    parts: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        if chunk.get("type") == "tool_calls":
            return ""
        if chunk.get("type") == "text_delta":
            parts.append(str(chunk.get("text", "")))
    return "".join(parts).strip()


# ── JSON helpers ──


def loads_json(text: str, *, error_label: str = "decision") -> dict[str, Any]:
    """Parse JSON from raw LLM output, tolerating markdown fences and noise."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError(f"{error_label} must be an object")
    return payload


# ── Confidence parsing (robust version from model_router.py) ──


def parse_confidence(value: Any) -> float | None:
    """Parse a confidence/score/probability value, normalising to 0-1."""
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        multiplier = 0.01 if text.endswith("%") else 1.0
        value = text.rstrip("%").strip()
    else:
        multiplier = 1.0
    try:
        confidence = float(value) * multiplier
    except (TypeError, ValueError):
        return None
    if confidence > 1.0:
        confidence /= 100.0
    return round(max(0.0, min(confidence, 1.0)), 4)


def decision_confidence(payload: dict[str, Any]) -> float:
    """Extract confidence from a model decision payload."""
    for key in ("confidence", "score", "probability", "prob"):
        confidence = parse_confidence(payload.get(key))
        if confidence is not None:
            return confidence
    return 0.0


# ── Marker-based detection helpers ──


def has_stock_style_target(text: str) -> bool:
    return any(marker in text for marker in STOCK_STYLE_MARKERS) and any(
        marker in text for marker in STOCK_STYLE_TARGETS
    )


def looks_like_portfolio_review(text: str) -> bool:
    compacted = compact_text(text)
    if not compacted:
        return False
    has_subject = any(marker in compacted for marker in PORTFOLIO_REVIEW_SUBJECT_MARKERS)
    has_strong_action = any(marker in compacted for marker in PORTFOLIO_REVIEW_STRONG_MARKERS)
    context_count = sum(1 for marker in PORTFOLIO_REVIEW_CONTEXT_MARKERS if marker in compacted)
    return has_subject and has_strong_action and context_count >= 1
