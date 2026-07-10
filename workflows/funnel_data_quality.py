"""Data-quality contract for production funnel runs."""

from __future__ import annotations

from collections import Counter

import pandas as pd

OHLCV_MIN_COVERAGE = 0.95
MARKET_CAP_MIN_COVERAGE = 0.95
FINANCIAL_MIN_COVERAGE = 0.90

_LAYER_REASONS = {
    "layer1": "ST/板块/市值/价格/流动性/财务准入",
    "layer2": "相对强弱/RPS/八通道条件",
    "layer3": "行业或概念板块共振",
    "layer4": "Spring/SOS/LPS/EVR买点确认",
}


def build_funnel_data_quality(
    symbols: list[str],
    df_map: dict[str, pd.DataFrame],
    market_cap_map: dict[str, float],
    financial_map: dict[str, dict],
    *,
    financial_requested: bool,
) -> dict:
    universe = list(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip()))
    total = len(universe)
    ohlcv_count = sum(1 for symbol in universe if _has_frame(df_map.get(symbol)))
    cap_count = sum(1 for symbol in universe if _positive_number(market_cap_map.get(symbol)))
    financial_count = sum(1 for symbol in universe if bool(financial_map.get(symbol)))
    coverage = {
        "ohlcv": _ratio(ohlcv_count, total),
        "market_cap": _ratio(cap_count, total),
        "financial": _ratio(financial_count, total),
    }
    reasons = _quality_reasons(coverage, financial_requested)
    source_counts = _ohlcv_source_counts(universe, df_map)
    return {
        "status": "degraded" if reasons else "normal",
        "trade_readiness": "observe_only" if reasons else "ready",
        "reasons": reasons,
        "financial_requested": bool(financial_requested),
        "coverage": coverage,
        "counts": {"universe": total, "ohlcv": ohlcv_count, "market_cap": cap_count, "financial": financial_count},
        "thresholds": {
            "ohlcv": OHLCV_MIN_COVERAGE,
            "market_cap": MARKET_CAP_MIN_COVERAGE,
            "financial": FINANCIAL_MIN_COVERAGE,
        },
        "ohlcv_source_counts": source_counts,
        "ohlcv_source_ratios": {source: _ratio(count, ohlcv_count) for source, count in source_counts.items()},
    }


def build_layer_rejections(
    *,
    total_symbols: int,
    l1_symbols: list[str],
    l2_symbols: list[str],
    l3_symbols: list[str],
    triggers: dict[str, list[tuple[str, float]]],
) -> dict[str, dict[str, int | str]]:
    trigger_symbols = {str(code).strip() for rows in triggers.values() for code, _score in rows if str(code).strip()}
    stage_counts = (
        ("layer1", max(int(total_symbols), 0), len(l1_symbols)),
        ("layer2", len(l1_symbols), len(l2_symbols)),
        ("layer3", len(l2_symbols), len(l3_symbols)),
        ("layer4", len(l3_symbols), len(trigger_symbols)),
    )
    return {
        layer: {
            "input": input_count,
            "passed": passed_count,
            "rejected": max(input_count - passed_count, 0),
            "reason": _LAYER_REASONS[layer],
        }
        for layer, input_count, passed_count in stage_counts
    }


def _quality_reasons(coverage: dict[str, float], financial_requested: bool) -> list[str]:
    checks = [("ohlcv", OHLCV_MIN_COVERAGE), ("market_cap", MARKET_CAP_MIN_COVERAGE)]
    if financial_requested:
        checks.append(("financial", FINANCIAL_MIN_COVERAGE))
    return [f"{name}_coverage<{threshold:.0%}" for name, threshold in checks if coverage[name] < threshold]


def _ohlcv_source_counts(symbols: list[str], df_map: dict[str, pd.DataFrame]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for symbol in symbols:
        frame = df_map.get(symbol)
        if not _has_frame(frame):
            continue
        source = str(frame.attrs.get("upstream_source") or frame.attrs.get("source") or "unknown").strip()
        counts[source or "unknown"] += 1
    return dict(sorted(counts.items()))


def _has_frame(frame: pd.DataFrame | None) -> bool:
    return frame is not None and not frame.empty


def _positive_number(value: object) -> bool:
    try:
        return float(value or 0.0) > 0.0
    except (TypeError, ValueError):
        return False


def _ratio(count: int, total: int) -> float:
    return round(count / total, 4) if total > 0 else 0.0
