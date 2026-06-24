"""Recommendation-tracking persistence for HK/US market funnel jobs."""

from __future__ import annotations

import os
from typing import Any


def write_tracking_candidates_if_enabled(candidates: list[dict[str, Any]], market: str) -> None:
    if os.getenv("MARKET_FUNNEL_WRITE_DB", "").strip().lower() in {"1", "true", "yes"}:
        upsert_funnel_to_tracking(candidates, market)


def upsert_funnel_to_tracking(candidates: list[dict[str, Any]], market: str) -> None:
    if not candidates or market not in ("us", "hk"):
        return
    from integrations.recommendation_global import upsert_global_recommendations

    rows_by_date: dict[int, list[dict[str, Any]]] = {}
    skipped = 0
    for candidate in candidates:
        recommend_date = _candidate_trade_date(candidate)
        if recommend_date is None:
            skipped += 1
            continue
        rows_by_date.setdefault(recommend_date, []).append(_tracking_row(candidate))
    if not rows_by_date:
        raise ValueError("cannot resolve recommendation trade date from market histories")
    for recommend_date, rows in sorted(rows_by_date.items()):
        ok = upsert_global_recommendations(recommend_date, rows, market)
        print(f"[market-funnel] DB write: market={market}, date={recommend_date}, candidates={len(rows)}, ok={ok}")
        if not ok:
            raise RuntimeError(f"DB write failed for market={market}, candidates={len(rows)}")
    if skipped:
        print(f"[market-funnel] DB write skipped candidates without trade date: {skipped}/{len(candidates)}")


def _candidate_trade_date(candidate: dict[str, Any]) -> int | None:
    try:
        date_int = int(candidate.get("latest_trade_date"))
    except (TypeError, ValueError):
        return None
    return date_int if 19000101 <= date_int <= 29991231 else None


def _tracking_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(candidate.get("symbol", "")).strip(),
        "name": str(candidate.get("name", "")).strip(),
        "tag": ",".join(candidate.get("triggers") or []),
        "score": float(candidate.get("score") or 0),
        "latest_close": float(candidate.get("latest_close") or 0),
    }
