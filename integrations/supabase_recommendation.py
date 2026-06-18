"""
Supabase 形态复盘数据存取模块
"""

from __future__ import annotations

import json
import logging
import os
from bisect import bisect_right
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from core.constants import (
    TABLE_RECOMMENDATION_TRACKING,
    TABLE_RECOMMENDATION_TRACKING_HK,
    TABLE_RECOMMENDATION_TRACKING_US,
)
from integrations.supabase_base import create_admin_client as _get_supabase_admin_client
from integrations.supabase_base import create_read_client as _get_supabase_read_client
from integrations.supabase_base import is_admin_configured as is_supabase_configured
from integrations.supabase_base import require_server_write_context

logger = logging.getLogger(__name__)
RECOMMENDATION_ATTRIBUTION_COLUMNS = (
    "primary_signal",
    "signal_types",
    "signal_track",
    "market_regime",
    "selection_source",
    "selection_rank",
    "selection_is_fill",
    "priority_score",
    "trigger_score",
    "stage",
    "industry",
    "sector_state_code",
    "sector_state",
    "sector_note",
    "sector_guidance",
    "exit_signal",
    "exit_price",
    "exit_reason",
    "strategic_theme",
    "strategic_theme_score",
    "strategic_stock_score",
    "strategic_theme_state",
    "strategic_theme_bonus",
    "springboard_a",
    "springboard_b",
    "springboard_c",
    "springboard_combo",
    "springboard_grade",
    "springboard_met_count",
    "springboard_support",
    "springboard_touch_count",
    "springboard_evidence",
    "springboard_scored",
)
RECOMMENDATION_OPTIONAL_COLUMNS = (
    "is_ai_recommended",
    "funnel_score",
    "recommend_count",
    *RECOMMENDATION_ATTRIBUTION_COLUMNS,
)
RECOMMENDATION_BACKUP_COLUMNS = (
    "code",
    "name",
    "recommend_reason",
    "recommend_date",
    "initial_price",
    "current_price",
    "change_pct",
    "recommend_count",
    "funnel_score",
    "is_ai_recommended",
    *RECOMMENDATION_ATTRIBUTION_COLUMNS,
    "updated_at",
)
SPRINGBOARD_AI_UPDATE_COLUMNS = (
    "springboard_a",
    "springboard_b",
    "springboard_c",
    "springboard_combo",
    "springboard_grade",
    "springboard_met_count",
    "springboard_support",
    "springboard_touch_count",
    "springboard_evidence",
    "springboard_scored",
)


def _fetch_all_tracking_records(client, select_expr: str = "*", page_size: int = 1000) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = max(min(int(page_size), 1000), 1)
    start = 0
    while True:
        resp = (
            client.table(TABLE_RECOMMENDATION_TRACKING)
            .select(select_expr)
            .order("recommend_date", desc=False)
            .order("id", desc=False)
            .range(start, start + page - 1)
            .execute()
        )
        batch = resp.data or []
        records.extend(batch)
        if len(batch) < page:
            return records
        start += page


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except Exception:
        return default
    return value if pd.notna(value) else default


def _code6(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    step = max(int(size), 1)
    return [items[i : i + step] for i in range(0, len(items), step)]


def _upsert_tracking_updates(client, updates: list[dict[str, Any]], batch_size: int = 500) -> int:
    written = 0
    clean_updates = [row for row in updates if row.get("code") is not None and row.get("recommend_date") is not None]
    for chunk in _chunked(clean_updates, max(min(int(batch_size), 1000), 1)):
        client.table(TABLE_RECOMMENDATION_TRACKING).upsert(chunk, on_conflict="code,recommend_date").execute()
        written += len(chunk)
    return written


def _resolve_tickflow_quote_price(quote: dict[str, Any] | None) -> float:
    row = quote or {}
    for key in ("last_price", "close", "last", "price", "current"):
        value = _safe_float(row.get(key), 0.0)
        if value > 0:
            return value
    return 0.0


def _quote_trade_date_yyyymmdd(quote: dict[str, Any] | None) -> str:
    timestamp_ms = _safe_float((quote or {}).get("timestamp"), 0.0)
    if timestamp_ms <= 0:
        return ""
    timestamp_s = timestamp_ms / 1000.0 if timestamp_ms > 10_000_000_000 else timestamp_ms
    try:
        return datetime.fromtimestamp(timestamp_s, UTC).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    except Exception:
        return ""


def _close_map_from_tickflow_hist(hist: pd.DataFrame | None) -> dict[str, float]:
    if hist is None or hist.empty or not {"date", "close"}.issubset(hist.columns):
        return {}
    work = hist[["date", "close"]].copy()
    work["trade_date"] = pd.to_datetime(work["date"], errors="coerce").dt.strftime("%Y%m%d")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["trade_date", "close"])
    work = work[work["close"] > 0]
    return {str(d): float(px) for d, px in zip(work["trade_date"], work["close"])}


def _ohlc_map_from_tickflow_hist(hist: pd.DataFrame | None) -> dict[str, dict[str, float]]:
    if hist is None or hist.empty or not {"date", "high", "low", "close"}.issubset(hist.columns):
        return {}
    work = hist[["date", "high", "low", "close"]].copy()
    work["trade_date"] = pd.to_datetime(work["date"], errors="coerce").dt.strftime("%Y%m%d")
    for col in ("high", "low", "close"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["trade_date", "high", "low", "close"])
    work = work[(work["high"] > 0) & (work["low"] > 0) & (work["close"] > 0)]
    return {
        str(row.trade_date): {"high": float(row.high), "low": float(row.low), "close": float(row.close)}
        for row in work.itertuples(index=False)
    }


def _fetch_tickflow_tracking_market_data(
    api_key: str,
    symbols: list[str],
    batch_size: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, pd.DataFrame]]:
    from integrations.tickflow_client import TickFlowClient

    tf_client = TickFlowClient(api_key=api_key)
    quotes: dict[str, dict[str, Any]] = {}
    hist_map: dict[str, pd.DataFrame] = {}
    for chunk in _chunked(symbols, batch_size):
        quotes.update(tf_client.get_quotes(chunk))
        hist_map.update(tf_client.get_klines_batch(chunk, period="1d", count=120, adjust="none"))
    return quotes, hist_map


def _build_tickflow_tracking_updates(
    grouped: dict[str, list[dict[str, Any]]],
    quotes: dict[str, dict[str, Any]],
    hist_map: dict[str, pd.DataFrame],
    now_iso: str,
) -> tuple[list[dict[str, Any]], int, str]:
    from integrations.tickflow_client import normalize_cn_symbol

    updates: list[dict[str, Any]] = []
    codes_no_data = 0
    latest_trade_date_global = ""
    for code6, rows in grouped.items():
        sym = normalize_cn_symbol(code6)
        quote = quotes.get(sym) or {}
        current_price = _resolve_tickflow_quote_price(quote)
        quote_trade_date = _quote_trade_date_yyyymmdd(quote)
        if quote_trade_date and quote_trade_date > latest_trade_date_global:
            latest_trade_date_global = quote_trade_date

        close_map = _close_map_from_tickflow_hist(hist_map.get(sym))
        trade_dates = sorted(close_map)
        if current_price <= 0 and trade_dates:
            current_price = float(close_map[trade_dates[-1]])
        if trade_dates and trade_dates[-1] > latest_trade_date_global:
            latest_trade_date_global = trade_dates[-1]
        if current_price <= 0 or not trade_dates:
            codes_no_data += 1
            continue

        for row in rows:
            rec_date = _recommend_date_to_yyyymmdd(row.get("recommend_date"))
            pick_date = _pick_close_on_or_before(trade_dates, rec_date)
            initial_close = float(close_map.get(pick_date, 0.0)) if pick_date else 0.0
            if initial_close <= 0:
                continue
            updates.append(
                {
                    "id": row.get("id"),
                    "code": int(code6),
                    "recommend_date": int(rec_date) if rec_date.isdigit() else None,
                    "initial_price": round(initial_close, 4),
                    "current_price": round(current_price, 4),
                    "change_pct": round((current_price - initial_close) / initial_close * 100.0, 2),
                    "updated_at": now_iso,
                }
            )
    return updates, codes_no_data, latest_trade_date_global


def _parse_recommend_date(raw_value: Any) -> date | None:
    if raw_value is None:
        return None
    s = str(raw_value).strip()
    if not s:
        return None
    try:
        if len(s) == 8 and s.isdigit():
            return datetime.strptime(s, "%Y%m%d").date()
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def _parse_write_date(record: dict[str, Any]) -> date | None:
    """优先用 recommend_date，没有则回退 created_at。"""
    rec_date = _parse_recommend_date(record.get("recommend_date"))
    if rec_date is not None:
        return rec_date

    created = record.get("created_at")
    if created is not None and str(created).strip():
        try:
            s = str(created).strip()
            if "T" in s or " " in s:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
            if len(s) == 8 and s.isdigit():
                return datetime.strptime(s, "%Y%m%d").date()
            return datetime.fromisoformat(s).date()
        except Exception:
            logger.debug("failed to parse created_at date: %s", created, exc_info=True)
    return None


def _resolve_initial_price_from_history(code_str: str, rec_date: date) -> float:
    """
    用推荐日附近历史日线回填加入价：
    1) 优先 rec_date 当天
    2) 若当天无数据，回看最近 7 天并取 <= rec_date 的最近交易日
    """
    try:
        from integrations.data_source import fetch_stock_hist

        rec_s = rec_date.strftime("%Y-%m-%d")
        hist = fetch_stock_hist(code_str, rec_s, rec_s, adjust="qfq")
        if hist is not None and not hist.empty:
            close_s = pd.to_numeric(hist.get("收盘"), errors="coerce").dropna()
            if not close_s.empty:
                px = float(close_s.iloc[-1])
                if px > 0:
                    return px

        start_s = (rec_date - timedelta(days=7)).strftime("%Y-%m-%d")
        hist2 = fetch_stock_hist(code_str, start_s, rec_s, adjust="qfq")
        if hist2 is None or hist2.empty:
            return 0.0
        df = hist2.copy()
        if "日期" not in df.columns or "收盘" not in df.columns:
            return 0.0
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
        df["收盘"] = pd.to_numeric(df["收盘"], errors="coerce")
        df = df.dropna(subset=["日期", "收盘"]).sort_values("日期")
        if df.empty:
            return 0.0
        df = df[df["日期"].dt.date <= rec_date]
        if df.empty:
            return 0.0
        px = float(df["收盘"].iloc[-1])
        return px if px > 0 else 0.0
    except Exception:
        return 0.0


def _load_existing_recommendation_history(client) -> tuple[dict[int, int], dict[int, set[int]]]:
    existing_counts: dict[int, int] = {}
    existing_code_dates: dict[int, set[int]] = {}
    all_rows = _fetch_all_tracking_records(client, "code,recommend_count,recommend_date")
    for row in all_rows:
        try:
            code_int = int(row.get("code"))
        except (TypeError, ValueError):
            continue
        cnt = int(row.get("recommend_count") or 1) if row.get("recommend_count") else 1
        existing_counts[code_int] = max(existing_counts.get(code_int, 0), cnt)
        try:
            d = int(row.get("recommend_date"))
            existing_code_dates.setdefault(code_int, set()).add(d)
        except (TypeError, ValueError):
            logger.debug("invalid recommend_date for code %s", row.get("code"), exc_info=True)
    return existing_counts, existing_code_dates


def _extract_recommendation_code(raw_code: Any) -> int | None:
    code_str = "".join(filter(str.isdigit, str(raw_code or "").strip()))
    return int(code_str) if code_str else None


def _extract_recommendation_price(row: dict[str, Any]) -> float:
    for key in ("initial_price", "current_price", "price", "latest_price", "close"):
        raw_price = row.get(key)
        if raw_price is None or raw_price == "":
            continue
        try:
            parsed = float(raw_price)
        except Exception:
            continue
        if parsed > 0:
            return parsed
    return 0.0


def _extract_recommendation_score(row: dict[str, Any]) -> float | None:
    for score_key in ("funnel_score", "score", "priority_score"):
        raw_score = row.get(score_key)
        if raw_score is None or raw_score == "":
            continue
        try:
            return float(raw_score)
        except Exception:
            continue
    return None


def _optional_text(raw: Any) -> str | None:
    text = str(raw or "").strip()
    return text or None


def _optional_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except Exception:
        return None
    return value if pd.notna(value) else None


def _optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _optional_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if raw is None or raw == "":
        return None
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _optional_text_list(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    values = raw if isinstance(raw, list | tuple | set) else str(raw).split(",")
    return [text for item in values if (text := str(item or "").strip())]


def _optional_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _springboard_combo(row: dict[str, Any]) -> str:
    combo = _optional_text(row.get("springboard_combo")) or _optional_text(row.get("springboard_grade"))
    if combo:
        return combo
    parts = [
        name
        for name, key in (("A", "springboard_a"), ("B", "springboard_b"), ("C", "springboard_c"))
        if _optional_bool(row.get(key))
    ]
    return "+".join(parts) if parts else "none"


def _extract_recommendation_attribution(row: dict[str, Any]) -> dict[str, Any]:
    signal_types = _optional_text_list(row.get("signal_types"))
    primary_signal = _optional_text(row.get("primary_signal")) or (signal_types[0] if signal_types else None)
    return {
        "primary_signal": primary_signal,
        "signal_types": signal_types,
        "signal_track": _optional_text(row.get("signal_track")) or _optional_text(row.get("track")),
        "market_regime": _optional_text(row.get("market_regime")),
        "selection_source": _optional_text(row.get("selection_source")),
        "selection_rank": _optional_int(row.get("selection_rank") or row.get("priority_rank")),
        "selection_is_fill": _optional_bool(row.get("selection_is_fill")) or False,
        "priority_score": _optional_float(row.get("priority_score")),
        "trigger_score": _optional_float(row.get("trigger_score") if "trigger_score" in row else row.get("score")),
        "stage": _optional_text(row.get("stage")),
        "industry": _optional_text(row.get("industry")),
        "sector_state_code": _optional_text(row.get("sector_state_code")),
        "sector_state": _optional_text(row.get("sector_state")),
        "sector_note": _optional_text(row.get("sector_note")),
        "sector_guidance": _optional_text(row.get("sector_guidance")),
        "exit_signal": _optional_text(row.get("exit_signal")),
        "exit_price": _optional_float(row.get("exit_price")),
        "exit_reason": _optional_text(row.get("exit_reason")),
        "strategic_theme": _optional_text(row.get("strategic_theme")),
        "strategic_theme_score": _optional_float(row.get("strategic_theme_score")),
        "strategic_stock_score": _optional_float(row.get("strategic_stock_score")),
        "strategic_theme_state": _optional_text(row.get("strategic_theme_state")),
        "strategic_theme_bonus": _optional_float(row.get("strategic_theme_bonus")),
        "springboard_a": _optional_bool(row.get("springboard_a")) or False,
        "springboard_b": _optional_bool(row.get("springboard_b")) or False,
        "springboard_c": _optional_bool(row.get("springboard_c")) or False,
        "springboard_combo": _springboard_combo(row),
        "springboard_grade": _optional_text(row.get("springboard_grade")) or _springboard_combo(row),
        "springboard_met_count": _optional_int(row.get("springboard_met_count")) or 0,
        "springboard_support": _optional_float(row.get("springboard_support")),
        "springboard_touch_count": _optional_int(row.get("springboard_touch_count")) or 0,
        "springboard_evidence": _optional_json(row.get("springboard_evidence")),
        "springboard_scored": _optional_bool(row.get("springboard_scored")) or False,
    }


def _is_missing_payload_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list | tuple | set):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    return False


def _copy_recommendation_attribution(target: dict[str, Any], source: dict[str, Any]) -> None:
    for col in RECOMMENDATION_ATTRIBUTION_COLUMNS:
        if not _is_missing_payload_value(source.get(col)) or _is_missing_payload_value(target.get(col)):
            target[col] = source.get(col)


def _merge_recommendation_payload_row(existing: dict[str, Any], row: dict[str, Any]) -> None:
    if not existing.get("name") and row.get("name"):
        existing["name"] = row["name"]
    old_score = existing.get("funnel_score")
    new_score = row.get("funnel_score")
    if new_score is not None and (old_score is None or float(new_score) > float(old_score)):
        existing["funnel_score"] = new_score
        existing["recommend_reason"] = row.get("recommend_reason", "")
        _copy_recommendation_attribution(existing, row)
    else:
        for col in RECOMMENDATION_ATTRIBUTION_COLUMNS:
            if _is_missing_payload_value(existing.get(col)) and not _is_missing_payload_value(row.get(col)):
                existing[col] = row[col]
    old_price = _safe_float(existing.get("initial_price"), 0.0)
    new_price = _safe_float(row.get("initial_price"), 0.0)
    if old_price <= 0 < new_price:
        existing["initial_price"] = new_price
        existing["current_price"] = new_price


def _build_recommendation_payload(
    recommend_date: int,
    symbols_info: list[dict[str, Any]],
    existing_counts: dict[int, int],
    existing_code_dates: dict[int, set[int]],
) -> list[dict[str, Any]]:
    payload_by_code: dict[int, dict[str, Any]] = {}
    for item in symbols_info:
        code_int = _extract_recommendation_code(item.get("code"))
        if code_int is None:
            continue
        old_cnt = existing_counts.get(code_int, 0)
        seen_dates = existing_code_dates.get(code_int, set())
        new_cnt = old_cnt if recommend_date in seen_dates else max(old_cnt, 0) + 1
        price = _extract_recommendation_price(item)
        row = {
            "code": code_int,
            "name": str(item.get("name", "")).strip(),
            "recommend_reason": str(item.get("tag", "")).strip(),
            "recommend_date": recommend_date,
            "initial_price": price,
            "current_price": price,
            "change_pct": 0.0,
            "recommend_count": new_cnt,
            "funnel_score": _extract_recommendation_score(item),
            "is_ai_recommended": False,
            "updated_at": datetime.now(UTC).isoformat(),
            **_extract_recommendation_attribution(item),
        }
        existing = payload_by_code.get(code_int)
        if existing:
            _merge_recommendation_payload_row(existing, row)
        else:
            payload_by_code[code_int] = row
    return list(payload_by_code.values())


def _upsert_recommendation_payload(client, payload: list[dict[str, Any]]) -> None:
    if not payload:
        return
    try:
        for chunk in _chunked(payload, 500):
            client.table(TABLE_RECOMMENDATION_TRACKING).upsert(chunk, on_conflict="code,recommend_date").execute()
    except Exception as e:
        msg = str(e).lower()
        if not any(col in msg for col in RECOMMENDATION_OPTIONAL_COLUMNS):
            raise
        fallback_payload: list[dict[str, Any]] = []
        for row in payload:
            r = dict(row)
            for col in RECOMMENDATION_OPTIONAL_COLUMNS:
                r.pop(col, None)
            fallback_payload.append(r)
        for chunk in _chunked(fallback_payload, 500):
            client.table(TABLE_RECOMMENDATION_TRACKING).upsert(chunk, on_conflict="code,recommend_date").execute()


def prepare_recommendation_payload(recommend_date: int, symbols_info: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not is_supabase_configured() or not symbols_info:
        return []
    client = _get_supabase_admin_client()
    existing_counts, existing_code_dates = _load_existing_recommendation_history(client)
    return _build_recommendation_payload(
        recommend_date,
        symbols_info,
        existing_counts,
        existing_code_dates,
    )


def upsert_recommendation_payload(payload: list[dict[str, Any]]) -> bool:
    if not is_supabase_configured() or not payload:
        return False
    require_server_write_context("upsert recommendation_tracking")
    try:
        client = _get_supabase_admin_client()
        _upsert_recommendation_payload(client, payload)
        return True
    except Exception as e:
        print(f"[supabase_recommendation] upsert_recommendation_payload failed: {e}")
        return False


def upsert_recommendations(recommend_date: int, symbols_info: list[dict[str, Any]]) -> bool:
    """
    将每日选出的股票存入形态复盘表
    recommend_date: YYYYMMDD (int)
    """
    if not is_supabase_configured() or not symbols_info:
        return False
    try:
        payload = prepare_recommendation_payload(recommend_date, symbols_info)

        # 使用 upsert，基于 (code, recommend_date) 唯一约束：
        # - 同一只股票在同一天重跑会覆盖更新；
        # - 跨天会新增一条记录；
        # - recommend_count 按 code 维度累计。
        return upsert_recommendation_payload(payload)
    except Exception as e:
        print(f"[supabase_recommendation] upsert_recommendations failed: {e}")
        return False


def _clean_backup_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list | tuple | set):
        return [cleaned for item in value if (cleaned := _clean_backup_value(item)) is not None]
    if isinstance(value, dict):
        return {str(key): cleaned for key, item in value.items() if (cleaned := _clean_backup_value(item)) is not None}
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _backup_rows(rows: list[dict[str, Any]], ai_codes: list[str] | None) -> list[dict[str, Any]]:
    ai_set = {_code6(code) for code in ai_codes or [] if _code6(code)}
    snapshot = []
    for row in rows:
        clean_row = {col: _clean_backup_value(row.get(col)) for col in RECOMMENDATION_BACKUP_COLUMNS if col in row}
        if ai_codes is not None:
            clean_row["is_ai_recommended"] = _code6(clean_row.get("code")) in ai_set
        snapshot.append(clean_row)
    return sorted(snapshot, key=lambda item: int(item.get("code") or 0))


def _sql_literal(value: Any) -> str:
    value = _clean_backup_value(value)
    if value is None:
        return "null"
    if isinstance(value, list):
        if not value:
            return "'{}'::text[]"
        return "array[" + ", ".join(_sql_literal(str(item)) for item in value) + "]::text[]"
    if isinstance(value, dict):
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _recommendation_restore_sql(rows: list[dict[str, Any]]) -> str:
    columns = [col for col in RECOMMENDATION_BACKUP_COLUMNS if any(col in row for row in rows)]
    if not rows or not columns:
        return "-- no recommendation rows to restore\n"
    values = []
    for row in rows:
        values.append("  (" + ", ".join(_sql_literal(row.get(col)) for col in columns) + ")")
    updates = ",\n  ".join(f"{col} = excluded.{col}" for col in columns if col not in {"code", "recommend_date"})
    return "\n".join(
        [
            "begin;",
            f"insert into public.{TABLE_RECOMMENDATION_TRACKING} ({', '.join(columns)})",
            "values",
            ",\n".join(values),
            "on conflict (code, recommend_date) do update set",
            f"  {updates};",
            "commit;",
            "",
        ]
    )


def write_recommendation_backup_artifact(
    recommend_date: int,
    rows: list[dict[str, Any]],
    output_dir: str,
    *,
    ai_codes: list[str] | None = None,
) -> list[str]:
    if not output_dir or not rows:
        return []
    snapshot = _backup_rows(rows, ai_codes)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    base = f"recommendation_tracking_{recommend_date}"
    json_path = target / f"{base}.json"
    sql_path = target / f"{base}.sql"
    payload = {
        "table": f"public.{TABLE_RECOMMENDATION_TRACKING}",
        "recommend_date": recommend_date,
        "row_count": len(snapshot),
        "generated_at": datetime.now(UTC).isoformat(),
        "rows": snapshot,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    sql_path.write_text(_recommendation_restore_sql(snapshot), encoding="utf-8")
    return [str(json_path), str(sql_path)]


def _ai_code_ints(ai_codes: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for code in ai_codes or []:
        code_digits = "".join(ch for ch in str(code) if ch.isdigit())
        if not code_digits:
            continue
        code6 = code_digits[-6:].zfill(6)
        try:
            out[code6] = int(code6)
        except Exception:
            continue
    return out


def _springboard_ai_payload(fields: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(fields, dict):
        return {}
    return {col: _clean_backup_value(fields[col]) for col in SPRINGBOARD_AI_UPDATE_COLUMNS if col in fields}


def mark_ai_recommendations(
    recommend_date: int,
    ai_codes: list[str],
    springboard_updates: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """
    将某个推荐日的记录标记为是否 AI 推荐（可操作池）。
    ai_codes 传入 6 位代码字符串列表。
    """
    if not is_supabase_configured():
        return False
    require_server_write_context("mark AI recommendations")
    try:
        client = _get_supabase_admin_client()
        now_iso = datetime.now(UTC).isoformat()
        # 先全量置 false，再对白名单置 true，避免前一次残留。
        client.table(TABLE_RECOMMENDATION_TRACKING).update({"is_ai_recommended": False, "updated_at": now_iso}).eq(
            "recommend_date", recommend_date
        ).execute()

        code_map = _ai_code_ints(ai_codes)
        if code_map:
            code_ints = sorted(set(code_map.values()))
            client.table(TABLE_RECOMMENDATION_TRACKING).update({"is_ai_recommended": True, "updated_at": now_iso}).eq(
                "recommend_date", recommend_date
            ).in_("code", code_ints).execute()
        updates = springboard_updates or {}
        for code6, code_int in code_map.items():
            payload = _springboard_ai_payload(updates.get(code6))
            if not payload:
                continue
            payload.update({"is_ai_recommended": True, "updated_at": now_iso})
            client.table(TABLE_RECOMMENDATION_TRACKING).update(payload).eq("recommend_date", recommend_date).eq(
                "code", code_int
            ).execute()
        return True
    except Exception as e:
        msg = str(e)
        if "is_ai_recommended" in msg:
            print(
                "[supabase_recommendation] mark_ai_recommendations skipped: "
                "missing column is_ai_recommended (please run SQL migration)"
            )
            return False
        print(f"[supabase_recommendation] mark_ai_recommendations failed: {e}")
        return False


def _resolve_price(code_str, price_map, history_fn, spot_fn) -> float | None:
    if price_map:
        try:
            px = float(price_map.get(code_str) or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px > 0:
            return px
    px = history_fn(code_str)
    if px is not None:
        return px
    return spot_fn(code_str)


def _build_price_update_row(record: dict, new_price: float, code_str: str, now_iso: str) -> dict:
    row: dict = {"id": record["id"], "current_price": new_price, "updated_at": now_iso}
    initial_price = float(record.get("initial_price") or 0.0)
    if initial_price > 0:
        row["change_pct"] = round((new_price - initial_price) / initial_price * 100.0, 2)
    else:
        rec_date = _parse_recommend_date(record.get("recommend_date"))
        backfill = _resolve_initial_price_from_history(code_str, rec_date) if rec_date else 0.0
        if backfill <= 0:
            backfill = new_price
        row["initial_price"] = backfill
        row["change_pct"] = round((new_price - backfill) / backfill * 100.0, 2) if backfill > 0 else 0.0
    return row


def sync_all_tracking_prices(
    price_map: dict[str, float] | None = None,
) -> int:
    """
    遍历表中所有股票，用最新价刷新 current_price 与 change_pct。
    price_map: 可选，code_str -> 最新收盘价。非空时优先使用；
    对缺失代码优先回退到历史日线收盘（qfq），最后才按开关尝试实时快照。
    返回成功更新的数量。
    """
    if not is_supabase_configured():
        print("[supabase_recommendation] sync_all_tracking_prices: Supabase 未配置，跳过")
        return 0
    require_server_write_context("sync recommendation_tracking prices")

    try:
        client = _get_supabase_admin_client()
        allow_spot_fallback = os.getenv("RECOMMENDATION_PRICE_ALLOW_SPOT_FALLBACK", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # 获取需要跟踪的股票代码（去重）
        code_rows = _fetch_all_tracking_records(client, "id,code")
        if not code_rows:
            print("[supabase_recommendation] sync_all_tracking_prices: 推荐表无记录，跳过")
            return 0

        unique_codes = sorted({int(r["code"]) for r in code_rows if r.get("code") is not None})

        # 统一日线窗口（与 step2 同口径），避免实时快照不稳定导致脏数据。
        hist_start_s: str | None = None
        hist_end_s: str | None = None
        hist_close_cache: dict[str, float] = {}
        try:
            from integrations.fetch_a_share_csv import _resolve_trading_window
            from utils.trading_clock import resolve_end_calendar_day

            window = _resolve_trading_window(
                end_calendar_day=resolve_end_calendar_day(),
                trading_days=20,
            )
            hist_start_s = window.start_trade_date.strftime("%Y-%m-%d")
            hist_end_s = window.end_trade_date.strftime("%Y-%m-%d")
        except Exception:
            hist_start_s = None
            hist_end_s = None

        def _price_from_history(code_str: str) -> float | None:
            if code_str in hist_close_cache:
                cached = hist_close_cache[code_str]
                return cached if cached > 0 else None
            if not hist_start_s or not hist_end_s:
                hist_close_cache[code_str] = 0.0
                return None
            try:
                from integrations.data_source import fetch_stock_hist

                hist = fetch_stock_hist(
                    code_str,
                    hist_start_s,
                    hist_end_s,
                    adjust="qfq",
                )
                if hist is None or hist.empty or "收盘" not in hist.columns:
                    hist_close_cache[code_str] = 0.0
                    return None
                close_s = pd.to_numeric(hist.get("收盘"), errors="coerce").dropna()
                if close_s.empty:
                    hist_close_cache[code_str] = 0.0
                    return None
                px = float(close_s.iloc[-1])
                hist_close_cache[code_str] = px if px > 0 else 0.0
                return px if px > 0 else None
            except Exception:
                hist_close_cache[code_str] = 0.0
                return None

        def _price_from_spot(code_str: str) -> float | None:
            if not allow_spot_fallback:
                return None
            try:
                from integrations.data_source import fetch_stock_spot_snapshot

                snap = fetch_stock_spot_snapshot(code_str, force_refresh=False)
                if not snap or snap.get("close") is None:
                    return None
                px = float(snap["close"])
                return px if px > 0 else None
            except Exception:
                return None

        all_records = _fetch_all_tracking_records(client, "*")
        records_by_code: dict[int, list[dict]] = {}
        for rec in all_records:
            try:
                c = int(rec.get("code"))
            except (TypeError, ValueError):
                continue
            records_by_code.setdefault(c, []).append(rec)

        updated_count = 0
        upsert_batch: list[dict] = []
        now_iso = datetime.now(UTC).isoformat()

        for code_int in unique_codes:
            code_str = f"{code_int:06d}"
            new_current_price = _resolve_price(code_str, price_map, _price_from_history, _price_from_spot)
            if new_current_price is None:
                continue
            for record in records_by_code.get(code_int, []):
                row = _build_price_update_row(record, new_current_price, code_str, now_iso)
                upsert_batch.append(row)
                if len(upsert_batch) >= 50:
                    client.table(TABLE_RECOMMENDATION_TRACKING).upsert(upsert_batch, on_conflict="id").execute()
                    updated_count += len(upsert_batch)
                    upsert_batch = []

        if upsert_batch:
            client.table(TABLE_RECOMMENDATION_TRACKING).upsert(upsert_batch, on_conflict="id").execute()
            updated_count += len(upsert_batch)

        if unique_codes and updated_count == 0:
            print(
                f"[supabase_recommendation] sync_all_tracking_prices: 推荐表有 {len(unique_codes)} 只股票但 0 条更新，"
                "可能是 price_map 为空且历史/实时行情均不可用"
            )
        return updated_count
    except Exception as e:
        print(f"[supabase_recommendation] sync_all_tracking_prices failed: {e}")
        return 0


def correct_tracking_initial_prices() -> int:
    """
    纠错流程：遍历推荐表每条记录，用「推荐日」当天收盘价（前复权）回填 initial_price，
    并用当前 current_price 重算 change_pct。
    每日执行可让历史数据逐步修正。
    返回被更新的记录数。
    """
    if not is_supabase_configured():
        print("[supabase_recommendation] correct_tracking_initial_prices: Supabase 未配置，跳过")
        return 0
    require_server_write_context("correct recommendation_tracking prices")
    try:
        client = _get_supabase_admin_client()
        records = _fetch_all_tracking_records(client, "*")
        if not records:
            return 0
        cache: dict[tuple[str, date], float] = {}
        updated = 0
        for record in records:
            write_date = _parse_write_date(record)
            if not write_date:
                continue
            code_int = record.get("code")
            if code_int is None:
                continue
            code_str = f"{int(code_int):06d}"
            current_price = float(record.get("current_price") or 0.0)
            if current_price <= 0:
                continue
            key = (code_str, write_date)
            if key not in cache:
                cache[key] = _resolve_initial_price_from_history(code_str, write_date)
            initial_from_hist = cache[key]
            if initial_from_hist <= 0:
                continue
            change_pct = round((current_price - initial_from_hist) / initial_from_hist * 100.0, 2)
            client.table(TABLE_RECOMMENDATION_TRACKING).update(
                {
                    "initial_price": initial_from_hist,
                    "change_pct": change_pct,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ).eq("id", record["id"]).execute()
            updated += 1
        return updated
    except Exception as e:
        print(f"[supabase_recommendation] correct_tracking_initial_prices failed: {e}")
        return 0


def load_recommendation_tracking(limit: int = 1000, client=None) -> list[dict[str, Any]]:
    """加载形态复盘数据"""
    try:
        if client is None:
            client = _get_supabase_read_client()
        resp = (
            client.table(TABLE_RECOMMENDATION_TRACKING)
            .select("*")
            .order("recommend_date", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[supabase_recommendation] load_recommendation_tracking failed: {e}")
        return []


def _to_ts_code_recommendation(symbol: str) -> str:
    s = "".join(ch for ch in str(symbol or "") if ch.isdigit())
    s = s[-6:].zfill(6)
    if s.startswith(("600", "601", "603", "605", "688")):
        return f"{s}.SH"
    return f"{s}.SZ"


def _recommend_date_to_yyyymmdd(raw: Any) -> str:
    d = _parse_recommend_date(raw)
    if d is None:
        return ""
    return d.strftime("%Y%m%d")


def _pick_close_on_or_before(sorted_trade_dates: list[str], target_yyyymmdd: str) -> str:
    if not sorted_trade_dates or not target_yyyymmdd:
        return ""
    i = bisect_right(sorted_trade_dates, target_yyyymmdd) - 1
    if i < 0:
        return ""
    return sorted_trade_dates[i]


def refresh_tracking_prices_with_tushare_unadjusted() -> dict[str, Any]:
    """
    使用 Tushare（日线不复权）回填并刷新形态复盘价格：
    - initial_price: 推荐日（或之前最近交易日）收盘价
    - current_price: 当前系统时间对应最近交易日收盘价
    - change_pct: (current - initial) / initial * 100
    """
    from integrations.tushare_client import get_pro

    if not is_supabase_configured():
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 未配置")
    require_server_write_context("refresh CN tracking prices with Tushare")

    pro = get_pro()
    if pro is None:
        raise ValueError("TUSHARE_TOKEN 未配置或 tushare 不可用")

    client = _get_supabase_admin_client()
    records = _fetch_all_tracking_records(client, "id,code,recommend_date")
    if not records:
        return {
            "rows_total": 0,
            "rows_updated": 0,
            "rows_skipped": 0,
            "codes_total": 0,
            "codes_no_data": 0,
            "latest_trade_date": "",
        }

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    end_date = today.strftime("%Y%m%d")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        code_digits = "".join(ch for ch in str(row.get("code", "")) if ch.isdigit())
        if not code_digits:
            continue
        code6 = code_digits[-6:].zfill(6)
        grouped.setdefault(code6, []).append(row)

    updates: list[dict[str, Any]] = []
    codes_no_data = 0
    latest_trade_date_global = ""

    for code6, rows in grouped.items():
        rec_dates = [_recommend_date_to_yyyymmdd(r.get("recommend_date")) for r in rows]
        rec_dates = [d for d in rec_dates if d]
        if not rec_dates:
            continue
        start_date = min(rec_dates)
        ts_code = _to_ts_code_recommendation(code6)

        try:
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception as e:
            print(f"[supabase_recommendation] tushare daily failed {ts_code}: {e}")
            codes_no_data += 1
            continue

        if df is None or df.empty:
            codes_no_data += 1
            continue

        work = df.copy()
        if "trade_date" not in work.columns or "close" not in work.columns:
            codes_no_data += 1
            continue
        work["trade_date"] = work["trade_date"].astype(str).str.replace(r"\.0$", "", regex=True)
        work["close"] = pd.to_numeric(work["close"], errors="coerce")
        work = work.dropna(subset=["trade_date", "close"])
        work = work[work["close"] > 0]
        if work.empty:
            codes_no_data += 1
            continue

        close_map = {str(td): float(px) for td, px in zip(work["trade_date"].tolist(), work["close"].tolist())}
        trade_dates = sorted(close_map.keys())
        current_trade_date = trade_dates[-1]
        current_close = float(close_map[current_trade_date])
        if not latest_trade_date_global or current_trade_date > latest_trade_date_global:
            latest_trade_date_global = current_trade_date

        for row in rows:
            rec_date = _recommend_date_to_yyyymmdd(row.get("recommend_date"))
            pick_date = _pick_close_on_or_before(trade_dates, rec_date)
            if not pick_date:
                continue
            initial_close = float(close_map[pick_date])
            if initial_close <= 0 or current_close <= 0:
                continue
            change_pct = round((current_close - initial_close) / initial_close * 100.0, 2)
            row_id = row.get("id")
            updates.append(
                {
                    "id": row_id,
                    "code": int(code6),
                    "recommend_date": int(rec_date) if rec_date.isdigit() else None,
                    "initial_price": round(initial_close, 4),
                    "current_price": round(current_close, 4),
                    "change_pct": change_pct,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )

    written = _upsert_tracking_updates(client, updates)

    return {
        "rows_total": len(records),
        "rows_updated": written,
        "rows_skipped": max(len(records) - written, 0),
        "codes_total": len(grouped),
        "codes_no_data": codes_no_data,
        "latest_trade_date": latest_trade_date_global,
    }


# ---------------------------------------------------------------------------
# US / HK 推荐表（独立表，code 为字符串如 AAPL.US / 00700.HK）
# ---------------------------------------------------------------------------

_MARKET_TABLE_MAP: dict[str, str] = {
    "us": TABLE_RECOMMENDATION_TRACKING_US,
    "hk": TABLE_RECOMMENDATION_TRACKING_HK,
}


def _resolve_global_table(market: str) -> str:
    table = _MARKET_TABLE_MAP.get(market.lower())
    if not table:
        raise ValueError(f"unsupported market: {market}, must be 'us' or 'hk'")
    return table


def _fetch_records_from_table(
    client,
    table: str,
    select_expr: str,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    start = 0
    page = max(min(int(page_size), 1000), 1)
    while True:
        resp = (
            client.table(table)
            .select(select_expr)
            .order("recommend_date", desc=False)
            .order("id", desc=False)
            .range(start, start + page - 1)
            .execute()
        )
        batch = resp.data or []
        records.extend(batch)
        if len(batch) < page:
            return records
        start += page


def _upsert_to_table(
    client,
    table: str,
    updates: list[dict[str, Any]],
    batch_size: int = 500,
) -> int:
    written = 0
    clean = [r for r in updates if r.get("code") and r.get("recommend_date")]
    for chunk in _chunked(clean, max(min(int(batch_size), 1000), 1)):
        client.table(table).upsert(chunk, on_conflict="code,recommend_date").execute()
        written += len(chunk)
    return written


def upsert_global_recommendations(
    recommend_date: int,
    candidates: list[dict[str, Any]],
    market: str,
) -> bool:
    table = _resolve_global_table(market)
    if not is_supabase_configured() or not candidates:
        return False
    require_server_write_context(f"upsert global recommendations {market}")
    try:
        client = _get_supabase_admin_client()
        payload = []
        for c in candidates:
            code = str(c.get("code") or c.get("symbol") or "").strip()
            if not code:
                continue
            price = _extract_price(c)
            score_val = _extract_score(c)
            payload.append(
                {
                    "code": code,
                    "name": str(c.get("name", "")).strip(),
                    "recommend_reason": str(c.get("tag") or c.get("recommend_reason") or "").strip(),
                    "recommend_date": recommend_date,
                    "initial_price": price,
                    "current_price": price,
                    "change_pct": 0.0,
                    "funnel_score": score_val,
                    "is_ai_recommended": False,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
        if payload:
            client.table(table).upsert(
                payload,
                on_conflict="code,recommend_date",
            ).execute()
        return True
    except Exception as e:
        print(f"[supabase_recommendation] upsert_global({market}) failed: {e}")
        return False


def _extract_price(c: dict[str, Any]) -> float:
    for key in ("initial_price", "latest_close", "current_price", "close"):
        raw = c.get(key)
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return 0.0


def _extract_score(c: dict[str, Any]) -> float | None:
    for sk in ("funnel_score", "score", "priority_score"):
        raw = c.get(sk)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def refresh_global_tracking_prices(market: str) -> dict[str, Any]:
    table = _resolve_global_table(market)
    if not is_supabase_configured():
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 未配置")
    require_server_write_context(f"refresh global tracking prices {market}")
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TICKFLOW_API_KEY 未配置")

    client = _get_supabase_admin_client()
    records = _fetch_records_from_table(client, table, "id,code,recommend_date")
    empty = {
        "rows_total": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
        "codes_total": 0,
        "codes_no_data": 0,
        "latest_trade_date": "",
    }
    if not records:
        return empty

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        code = str(row.get("code") or "").strip()
        if code:
            grouped.setdefault(code, []).append(row)

    symbols = sorted(grouped.keys())
    batch_size = max(min(int(os.getenv("RECOMMENDATION_TICKFLOW_BATCH_SIZE", "80")), 200), 1)
    quotes, hist_map = _fetch_tickflow_tracking_market_data(api_key, symbols, batch_size)

    updates: list[dict[str, Any]] = []
    codes_no_data = 0
    latest_td = ""
    now_iso = datetime.now(UTC).isoformat()

    for code, rows in grouped.items():
        quote = quotes.get(code) or {}
        cur = _resolve_tickflow_quote_price(quote)
        qtd = _quote_trade_date_yyyymmdd(quote)
        if qtd and qtd > latest_td:
            latest_td = qtd
        cmap = _close_map_from_tickflow_hist(hist_map.get(code))
        tdates = sorted(cmap)
        if cur <= 0 and tdates:
            cur = float(cmap[tdates[-1]])
        if tdates and tdates[-1] > latest_td:
            latest_td = tdates[-1]
        if cur <= 0 or not tdates:
            codes_no_data += 1
            continue
        for row in rows:
            rd = _recommend_date_to_yyyymmdd(row.get("recommend_date"))
            pd_ = _pick_close_on_or_before(tdates, rd)
            init = float(cmap.get(pd_, 0.0)) if pd_ else 0.0
            if init <= 0:
                continue
            updates.append(
                {
                    "id": row.get("id"),
                    "code": code,
                    "recommend_date": int(rd) if rd.isdigit() else None,
                    "initial_price": round(init, 4),
                    "current_price": round(cur, 4),
                    "change_pct": round((cur - init) / init * 100.0, 2),
                    "updated_at": now_iso,
                }
            )

    written = _upsert_to_table(client, table, updates)
    return {
        "rows_total": len(records),
        "rows_updated": written,
        "rows_skipped": max(len(records) - written, 0),
        "codes_total": len(grouped),
        "codes_no_data": codes_no_data,
        "latest_trade_date": latest_td,
    }


def _latest_market_records(records: list[dict[str, Any]], max_dates: int) -> list[dict[str, Any]]:
    limit = max(int(max_dates), 1)
    dates = sorted(
        {d for d in (_recommend_date_to_yyyymmdd(row.get("recommend_date")) for row in records) if d},
        reverse=True,
    )[:limit]
    allowed = set(dates)
    return [row for row in records if _recommend_date_to_yyyymmdd(row.get("recommend_date")) in allowed]


def _build_us_performance_update(
    row: dict[str, Any],
    code: str,
    ohlc: dict[str, dict[str, float]],
    now_iso: str,
) -> dict[str, Any] | None:
    trade_dates = sorted(ohlc)
    rd = _recommend_date_to_yyyymmdd(row.get("recommend_date"))
    entry_date = _pick_close_on_or_before(trade_dates, rd)
    if not entry_date:
        return None
    entry = _safe_float(ohlc.get(entry_date, {}).get("close"), 0.0)
    if entry <= 0:
        entry = _safe_float(row.get("initial_price"), 0.0)
    if entry <= 0:
        return None
    window = [(d, ohlc[d]) for d in trade_dates if d >= entry_date]
    if not window:
        return None
    high_date, high_row = max(window, key=lambda item: item[1]["high"])
    low_date, low_row = min(window, key=lambda item: item[1]["low"])
    latest_date, latest_row = window[-1]
    mfe_price = float(high_row["high"])
    mae_price = float(low_row["low"])
    current_price = float(latest_row["close"])
    return {
        "id": row.get("id"),
        "code": code,
        "recommend_date": int(rd) if rd.isdigit() else None,
        "initial_price": round(entry, 4),
        "current_price": round(current_price, 4),
        "change_pct": round((current_price / entry - 1.0) * 100.0, 2),
        "mfe_pct": round((mfe_price / entry - 1.0) * 100.0, 2),
        "mae_pct": round((mae_price / entry - 1.0) * 100.0, 2),
        "range_amp_pct": round((mfe_price / mae_price - 1.0) * 100.0, 2) if mae_price > 0 else 0.0,
        "mfe_price": round(mfe_price, 4),
        "mae_price": round(mae_price, 4),
        "mfe_date": int(high_date),
        "mae_date": int(low_date),
        "performance_days": len(window),
        "performance_updated_at": now_iso,
        "updated_at": now_iso,
    }


def refresh_us_tracking_performance(max_dates: int = 60, kline_count: int = 160) -> dict[str, Any]:
    if not is_supabase_configured():
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 未配置")
    require_server_write_context("refresh US tracking performance")
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TICKFLOW_API_KEY 未配置")

    client = _get_supabase_admin_client()
    table = TABLE_RECOMMENDATION_TRACKING_US
    records = _fetch_records_from_table(client, table, "id,code,recommend_date,initial_price")
    records = _latest_market_records(records, max_dates)
    if not records:
        return _empty_us_performance_summary()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        code = str(row.get("code") or "").strip()
        if code:
            grouped.setdefault(code, []).append(row)

    from integrations.tickflow_client import TickFlowClient

    tf_client = TickFlowClient(api_key=api_key)
    symbols = sorted(grouped)
    hist_map = tf_client.get_klines_batch(symbols, period="1d", count=max(int(kline_count), 1), adjust="forward")
    now_iso = datetime.now(UTC).isoformat()
    updates, codes_no_data, latest_td = _build_us_performance_updates(grouped, hist_map, now_iso)
    written = _upsert_to_table(client, table, updates)
    return _us_performance_summary(records, grouped, written, codes_no_data, latest_td, updates)


def _build_us_performance_updates(
    grouped: dict[str, list[dict[str, Any]]],
    hist_map: dict[str, pd.DataFrame],
    now_iso: str,
) -> tuple[list[dict[str, Any]], int, str]:
    updates: list[dict[str, Any]] = []
    codes_no_data = 0
    latest_td = ""
    for code, rows in grouped.items():
        ohlc = _ohlc_map_from_tickflow_hist(hist_map.get(code))
        trade_dates = sorted(ohlc)
        if not trade_dates:
            codes_no_data += 1
            continue
        latest_td = max(latest_td, trade_dates[-1])
        for row in rows:
            update = _build_us_performance_update(row, code, ohlc, now_iso)
            if update is not None:
                updates.append(update)
    return updates, codes_no_data, latest_td


def _empty_us_performance_summary() -> dict[str, Any]:
    return {
        "rows_total": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
        "codes_total": 0,
        "codes_no_data": 0,
        "latest_trade_date": "",
        "mfe_ge_5": 0,
        "mfe_ge_10": 0,
        "mae_le_neg5": 0,
    }


def _us_performance_summary(
    records: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    written: int,
    codes_no_data: int,
    latest_trade_date: str,
    updates: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = _empty_us_performance_summary()
    summary.update(
        {
            "rows_total": len(records),
            "rows_updated": written,
            "rows_skipped": max(len(records) - written, 0),
            "codes_total": len(grouped),
            "codes_no_data": codes_no_data,
            "latest_trade_date": latest_trade_date,
            "mfe_ge_5": sum(_safe_float(row.get("mfe_pct")) >= 5.0 for row in updates),
            "mfe_ge_10": sum(_safe_float(row.get("mfe_pct")) >= 10.0 for row in updates),
            "mae_le_neg5": sum(_safe_float(row.get("mae_pct")) <= -5.0 for row in updates),
        }
    )
    return summary


def refresh_tracking_prices_with_tickflow_realtime() -> dict[str, Any]:
    """
    使用 Tickflow 实时报价刷新形态复盘价格：
    - current_price: Tickflow /v1/quotes 的 last_price
    - initial_price: 推荐日（或之前最近交易日）Tickflow 不复权日线收盘价
    - change_pct: (current - initial) / initial * 100
    """
    if not is_supabase_configured():
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 未配置")
    require_server_write_context("refresh CN tracking prices")

    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TICKFLOW_API_KEY 未配置")

    from integrations.tickflow_client import normalize_cn_symbol

    client = _get_supabase_admin_client()
    records = _fetch_all_tracking_records(client, "id,code,recommend_date")
    if not records:
        return {
            "rows_total": 0,
            "rows_updated": 0,
            "rows_skipped": 0,
            "codes_total": 0,
            "codes_no_data": 0,
            "latest_trade_date": "",
        }

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        code6 = _code6(row.get("code"))
        if code6:
            grouped.setdefault(code6, []).append(row)

    symbols = [normalize_cn_symbol(code6) for code6 in sorted(grouped)]
    symbols = [sym for sym in symbols if sym]
    batch_size = max(min(int(os.getenv("RECOMMENDATION_TICKFLOW_BATCH_SIZE", "80")), 200), 1)
    quotes, hist_map = _fetch_tickflow_tracking_market_data(api_key, symbols, batch_size)
    updates, codes_no_data, latest_trade_date_global = _build_tickflow_tracking_updates(
        grouped,
        quotes,
        hist_map,
        datetime.now(UTC).isoformat(),
    )

    written = _upsert_tracking_updates(client, updates)

    return {
        "rows_total": len(records),
        "rows_updated": written,
        "rows_skipped": max(len(records) - written, 0),
        "codes_total": len(grouped),
        "codes_no_data": codes_no_data,
        "latest_trade_date": latest_trade_date_global,
    }
