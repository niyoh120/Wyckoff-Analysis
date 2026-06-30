"""Evaluate recommendation rows against fixed-horizon price targets."""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.constants import TABLE_SIGNAL_OBSERVATIONS
from core.recommendation_event_metrics import build_horizon_event, summarize_horizon_events
from integrations.recommendation_performance import (
    TRACKING_TABLE_BY_MARKET,
    group_records_by_market_code,
    latest_market_records,
    resolve_tracking_market,
)
from integrations.recommendation_tracking_common import chunked, ohlc_map_from_tickflow_hist, recommend_date_to_yyyymmdd
from integrations.supabase_base import create_admin_client, is_admin_configured


@dataclass(frozen=True)
class RecommendationEventEvalRequest:
    market: str = "cn"
    horizon_days: int = 5
    target_pct: float = 10.0
    max_dates: int = 30
    kline_count: int = 160
    output_dir: str = "artifacts/recommendation_event_eval"
    top_k: tuple[int, ...] = (1, 3, 5)


def run_recommendation_event_eval(request: RecommendationEventEvalRequest) -> int:
    result = build_recommendation_event_eval(request)
    output_dir = Path(request.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "summary.json", result["summary"])
    _write_json(output_dir / "events.json", result["events"])
    _write_markdown(output_dir / "summary.md", result)
    summary = result["summary"]["all"]
    print(
        "[recommendation-event-eval] "
        f"ready={summary['rows_ready']}/{summary['rows_total']} "
        f"hit_rate={summary['hit_rate_pct']}% "
        f"target={request.target_pct}%/{request.horizon_days}d"
    )
    print(f"[recommendation-event-eval] wrote {output_dir}")
    return 0


def build_recommendation_event_eval(request: RecommendationEventEvalRequest) -> dict[str, Any]:
    if not is_admin_configured():
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 未配置")
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TICKFLOW_API_KEY 未配置")

    market = resolve_tracking_market(request.market)
    records = _fetch_records(market, request.max_dates)
    feature_map = _fetch_observation_feature_map(market, records)
    grouped = group_records_by_market_code(records, market)
    hist_by_code = _fetch_hist_by_code(api_key, sorted(grouped), market, request.kline_count)
    events = _build_events(grouped, hist_by_code, request, feature_map)
    summary = _build_summary(events, request.top_k)
    return {
        "metadata": _metadata(request, market, records, grouped),
        "summary": summary,
        "daily": _daily_summary(events),
        "events": events,
    }


def _fetch_records(market: str, max_dates: int) -> list[dict[str, Any]]:
    table = TRACKING_TABLE_BY_MARKET[market]
    client = create_admin_client()
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        resp = client.table(table).select("*").order("recommend_date", desc=False).range(start, start + 999).execute()
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < 1000:
            return latest_market_records(rows, max_dates)
        start += 1000


def _fetch_observation_feature_map(
    market: str,
    records: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    dates = sorted({_date_iso(recommend_date_to_yyyymmdd(row.get("recommend_date"))) for row in records})
    dates = [day for day in dates if day]
    if not dates:
        return {}
    client = create_admin_client()
    rows: list[dict[str, Any]] = []
    try:
        for batch in chunked(dates, 100):
            resp = (
                client.table(TABLE_SIGNAL_OBSERVATIONS)
                .select("trade_date,code,features_json")
                .eq("market", market)
                .in_("trade_date", batch)
                .execute()
            )
            rows.extend(resp.data or [])
    except Exception:
        return {}
    return _observation_feature_map(rows, market)


def _observation_feature_map(rows: list[dict[str, Any]], market: str = "cn") -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (_code_key(row.get("code"), market), _date_compact(row.get("trade_date")))
        features = _json_map(row.get("features_json"))
        if key[0] and key[1] and features:
            out[key] = _merge_quality_features(out.get(key, {}), features)
    return out


def _fetch_hist_by_code(
    api_key: str,
    codes: list[str],
    market: str,
    kline_count: int,
) -> dict[str, pd.DataFrame | None]:
    symbol_map = _tickflow_symbol_map(codes, market)
    hist_map = _fetch_histories(api_key, sorted(set(symbol_map.values())), kline_count)
    return {code: hist_map.get(symbol) for code, symbol in symbol_map.items()}


def _tickflow_symbol_map(codes: list[str], market: str) -> dict[str, str]:
    if market != "cn":
        return {code: code for code in codes if code}
    from integrations.tickflow_client import normalize_cn_symbol

    return {code: symbol for code in codes if (symbol := normalize_cn_symbol(code))}


def _fetch_histories(api_key: str, symbols: list[str], kline_count: int) -> dict[str, pd.DataFrame]:
    from integrations.tickflow_client import TickFlowClient

    client = TickFlowClient(api_key=api_key)
    hist_map: dict[str, pd.DataFrame] = {}
    for batch in chunked(symbols, _batch_size()):
        hist_map.update(client.get_klines_batch(batch, period="1d", count=max(int(kline_count), 1), adjust="forward"))
    return hist_map


def _build_events(
    grouped: dict[str, list[dict[str, Any]]],
    hist_by_code: dict[str, pd.DataFrame | None],
    request: RecommendationEventEvalRequest,
    feature_map: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    feature_map = feature_map or {}
    for code, rows in sorted(grouped.items()):
        ohlc = ohlc_map_from_tickflow_hist(hist_by_code.get(code))
        events.extend(_event_with_quality(row, code, ohlc, request, feature_map) for row in rows)
    return sorted(events, key=lambda item: (item.get("recommend_date") or 0, str(item.get("code") or "")))


def _event_with_quality(
    row: dict[str, Any],
    code: str,
    ohlc: dict[str, dict[str, float]],
    request: RecommendationEventEvalRequest,
    feature_map: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    event = build_horizon_event(row, ohlc, horizon_days=request.horizon_days, target_pct=request.target_pct)
    key = (_code_key(code, resolve_tracking_market(request.market)), _date_compact(row.get("recommend_date")))
    return {**event, **_quality_feature_fields(row, feature_map.get(key, {}))}


def _build_summary(events: list[dict[str, Any]], top_k: tuple[int, ...]) -> dict[str, Any]:
    top_k_by_strategy = _top_k_by_strategy(events, top_k)
    summary = {
        "all": summarize_horizon_events(events),
        "ai": summarize_horizon_events([event for event in events if event.get("is_ai_recommended")]),
        "non_ai": summarize_horizon_events([event for event in events if not event.get("is_ai_recommended")]),
        "top_k": top_k_by_strategy["score_only"],
        "top_k_by_strategy": top_k_by_strategy,
        "candidate_shadow_grade": _grade_summary(events, "candidate_shadow_grade"),
        "entry_quality_grade": _grade_summary(events, "entry_quality_grade"),
    }
    return summary


def _grade_summary(events: list[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        groups[_grade(event.get(field))].append(event)
    order = ("S", "A", "B", "C", "D", "unknown")
    return {grade: summarize_horizon_events(groups[grade]) for grade in order if grade in groups}


def _top_k_by_strategy(events: list[dict[str, Any]], top_k: tuple[int, ...]) -> dict[str, dict[str, Any]]:
    strategies = ["score_only", "ai_then_score", "recommend_count"]
    return {
        strategy: {str(k): _top_k_summary(events, k, strategy) for k in sorted({max(int(value), 1) for value in top_k})}
        for strategy in strategies
    }


def _top_k_summary(events: list[dict[str, Any]], k: int, strategy: str = "score_only") -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for rows in _events_by_date(events).values():
        selected.extend(_rank_events(rows, strategy)[:k])
    summary = summarize_horizon_events(selected)
    summary["days_covered"] = len(_events_by_date(events))
    summary["top_k"] = k
    summary["ranking"] = strategy
    return summary


def _daily_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rec_date, day_events in sorted(_events_by_date(events).items()):
        summary = summarize_horizon_events(day_events)
        rows.append({"recommend_date": rec_date, **summary})
    return rows


def _events_by_date(events: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        rec_date = event.get("recommend_date")
        if rec_date:
            grouped[int(rec_date)].append(event)
    return dict(grouped)


def _rank_events(events: list[dict[str, Any]], strategy: str) -> list[dict[str, Any]]:
    return sorted(events, key=lambda event: _rank_key(event, strategy), reverse=True)


def _rank_key(event: dict[str, Any], strategy: str) -> tuple[float, float, float, str]:
    ai = 1.0 if event.get("is_ai_recommended") else 0.0
    score = _number(event.get("funnel_score"), -1.0)
    count = _number(event.get("recommend_count"), 0.0)
    code = str(event.get("code") or "")
    if strategy == "ai_then_score":
        return ai, score, count, code
    if strategy == "recommend_count":
        return count, score, ai, code
    return score, ai, count, code


def _metadata(
    request: RecommendationEventEvalRequest,
    market: str,
    records: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "market": market,
        "horizon_days": request.horizon_days,
        "target_pct": request.target_pct,
        "max_dates": request.max_dates,
        "kline_count": request.kline_count,
        "records": len(records),
        "codes": len(grouped),
    }


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    meta = result["metadata"]
    lines = [
        "# Recommendation Event Evaluation",
        "",
        f"- Market: `{meta['market']}`",
        f"- Target: `{meta['target_pct']}%` within `{meta['horizon_days']}` future trading days",
        f"- Records: `{meta['records']}` rows / `{meta['codes']}` codes",
        "",
        "| Slice | Ready | Hit rate | Close win | Avg close | Payoff | Avg MFE | Avg MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(_summary_markdown_rows(result["summary"]))
    lines.extend(_strategy_markdown(result["summary"]["top_k_by_strategy"]))
    lines.extend(_quality_markdown(result["summary"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _summary_markdown_rows(summary: dict[str, Any]) -> list[str]:
    rows = [_summary_row("all", summary["all"]), _summary_row("ai", summary["ai"])]
    rows.extend(_summary_row(f"top{k}", item) for k, item in summary["top_k"].items())
    return rows


def _strategy_markdown(top_k_by_strategy: dict[str, dict[str, Any]]) -> list[str]:
    rows = [
        "",
        "## Ranking Strategy Comparison",
        "",
        "| Strategy | Top-K | Ready | Hit rate | Close win | Avg close | Payoff | Avg MFE | Avg MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy, top_rows in top_k_by_strategy.items():
        for k, item in top_rows.items():
            ready = f"{item.get('rows_ready', 0)}/{item.get('rows_total', 0)}"
            rows.append(
                f"| {strategy} | {k} | {ready} | {_fmt(item.get('hit_rate_pct'))}% | "
                f"{_fmt(item.get('close_win_rate_pct'))}% | {_fmt(item.get('avg_close_return_horizon_pct'))}% | "
                f"{_fmt(item.get('close_payoff_ratio'))} | {_fmt(item.get('avg_mfe_horizon_pct'))}% | "
                f"{_fmt(item.get('avg_mae_horizon_pct'))}% |"
            )
    return rows


def _quality_markdown(summary: dict[str, Any]) -> list[str]:
    rows = ["", "## Candidate Quality Slices"]
    rows.extend(_quality_table("Candidate shadow grade", summary.get("candidate_shadow_grade") or {}))
    rows.extend(_quality_table("Entry quality grade", summary.get("entry_quality_grade") or {}))
    return rows


def _quality_table(title: str, grade_rows: dict[str, Any]) -> list[str]:
    rows = [
        "",
        f"### {title}",
        "",
        "| Grade | Ready | Hit rate | Close win | Avg close | Payoff | Avg MFE | Avg MAE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if not grade_rows:
        return [*rows, "| n/a | 0/0 | n/a | n/a | n/a | n/a | n/a | n/a |"]
    return [*rows, *(_summary_row(grade, item) for grade, item in grade_rows.items())]


def _summary_row(label: str, row: dict[str, Any]) -> str:
    ready = f"{row.get('rows_ready', 0)}/{row.get('rows_total', 0)}"
    return (
        f"| {label} | {ready} | {_fmt(row.get('hit_rate_pct'))}% | "
        f"{_fmt(row.get('close_win_rate_pct'))}% | {_fmt(row.get('avg_close_return_horizon_pct'))}% | "
        f"{_fmt(row.get('close_payoff_ratio'))} | {_fmt(row.get('avg_mfe_horizon_pct'))}% | "
        f"{_fmt(row.get('avg_mae_horizon_pct'))}% |"
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _number(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _quality_feature_fields(row: dict[str, Any], observed_features: dict[str, Any] | None = None) -> dict[str, Any]:
    features = _merge_quality_features(_json_map(observed_features), _json_map(row.get("features_json")))
    shadow = _json_map(features.get("candidate_shadow_score"))
    entry = _json_map(features.get("entry_quality"))
    return {
        "candidate_shadow_score": _optional_number(shadow.get("score")),
        "candidate_shadow_grade": _grade(shadow.get("grade")),
        "entry_quality_score": _optional_number(entry.get("score")),
        "entry_quality_grade": _grade(entry.get("grade")),
        "entry_quality_risk_flags": _str_list(entry.get("risk_flags")),
    }


def _merge_quality_features(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in ("candidate_shadow_score", "entry_quality"):
        value = _json_map(overlay.get(key))
        if value:
            merged[key] = value
    return merged


def _json_map(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _grade(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    return text if text in {"S", "A", "B", "C", "D"} else "unknown"


def _optional_number(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return round(value, 2) if math.isfinite(value) else None


def _str_list(raw: Any) -> list[str]:
    if isinstance(raw, list | tuple | set):
        return [text for item in raw if (text := str(item or "").strip())]
    text = str(raw or "").strip()
    return [text] if text else []


def _code_key(raw: Any, market: str) -> str:
    text = str(raw or "").strip()
    if market == "cn":
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits[-6:].zfill(6) if digits else ""
    return text.upper()


def _date_iso(raw: Any) -> str:
    text = _date_compact(raw)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}" if len(text) == 8 else ""


def _date_compact(raw: Any) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())[:8]


def _fmt(raw: Any) -> str:
    return "n/a" if raw is None else str(raw)


def _batch_size() -> int:
    raw = os.getenv("RECOMMENDATION_EVENT_EVAL_BATCH_SIZE", "").strip()
    try:
        return max(min(int(float(raw or 80)), 100), 1)
    except (TypeError, ValueError):
        return 80
