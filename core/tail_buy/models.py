from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DECISION_BUY = "BUY"
DECISION_WATCH = "WATCH"
DECISION_SKIP = "SKIP"
VALID_DECISIONS = {DECISION_BUY, DECISION_WATCH, DECISION_SKIP}


@dataclass
class TailBuyCandidate:
    code: str
    name: str
    signal_date: str
    status: str
    signal_type: str
    signal_score: float
    market_regime: str = ""
    candidate_lane: str = ""
    entry_type: str = ""
    signal_key: str = ""
    candidate_status: str = ""
    snap: dict[str, Any] = field(default_factory=dict)
    rule_score: float = 0.0
    rule_decision: str = DECISION_SKIP
    rule_reasons: list[str] = field(default_factory=list)
    llm_decision: str | None = None
    llm_reason: str = ""
    llm_confidence: float | None = None
    llm_model_used: str = ""
    final_decision: str = DECISION_SKIP
    priority_score: float = 0.0
    fetch_error: str = ""
    features: dict[str, Any] = field(default_factory=dict)
    summary_5m: str = ""


def normalize_cn_code(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "").strip() if ch.isdigit())
    if not digits:
        return ""
    if len(digits) > 6:
        digits = digits[-6:]
    return digits.zfill(6)


def normalize_status(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    return text if text else "pending"


def normalize_regime(raw: Any) -> str:
    return str(raw or "").strip().upper()


def safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        if raw is None:
            return default
        text = str(raw).strip()
        if not text:
            return default
        return float(text)
    except Exception:
        return default
