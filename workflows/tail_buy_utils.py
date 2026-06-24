"""Shared runtime helpers for tail-buy workflows."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from integrations.tickflow_notice import TICKFLOW_LIMIT_HINT

TZ = ZoneInfo("Asia/Shanghai")
TICKFLOW_UPGRADE_HINT = TICKFLOW_LIMIT_HINT


def current_time() -> datetime:
    return datetime.now(TZ)


def now_text() -> str:
    return current_time().strftime("%Y-%m-%d %H:%M:%S")


def log_line(msg: str, logs_path: str | None = None) -> None:
    line = f"[{now_text()}] {msg}"
    print(line, flush=True)
    if logs_path:
        os.makedirs(os.path.dirname(logs_path) or ".", exist_ok=True)
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def remaining_seconds(deadline_at: datetime) -> float:
    return (deadline_at - current_time()).total_seconds()


def chunked(seq: list[Any], chunk_size: int) -> list[list[Any]]:
    size = max(int(chunk_size), 1)
    return [seq[i : i + size] for i in range(0, len(seq), size)]


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


def normalize_code6(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def resolve_quote_price(quote: dict[str, Any] | None) -> float:
    row = quote or {}
    for key in ("last_price", "close", "last", "price", "current"):
        value = safe_float(row.get(key), 0.0)
        if value > 0:
            return value
    return 0.0


def with_tickflow_upgrade_hint(message: str) -> str:
    text = str(message or "").strip()
    if not text or TICKFLOW_UPGRADE_HINT in text:
        return text
    if _is_tickflow_upgrade_related_error(text):
        return f"{text}（{TICKFLOW_UPGRADE_HINT}）"
    return text


def _is_tickflow_upgrade_related_error(err_or_text: Any) -> bool:
    text = str(err_or_text or "").lower()
    if not text:
        return False
    markers = (
        "tickflow http 429",
        "http 429",
        "rate_limited",
        "too many requests",
        "限流",
        "forbidden",
        "套餐不支持",
        "不支持日内批量查询",
        "not support intraday batch",
        "permission denied",
    )
    return any(m in text for m in markers)
