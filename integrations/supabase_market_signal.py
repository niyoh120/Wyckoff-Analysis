# -*- coding: utf-8 -*-
"""
Supabase 最新交易日市场信号读写

用途：
1) 定时任务写入 A50 / VIX / 大盘水温
2) Web 端读取最新交易日市场信号并渲染全局提示栏
"""
from __future__ import annotations

from datetime import date, datetime
import os
from typing import Any

from supabase import Client, create_client

from core.constants import TABLE_MARKET_SIGNAL_DAILY


def _get_supabase_admin_client() -> Client:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (
        (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        or (os.getenv("SUPABASE_KEY") or "").strip()
    )
    if not url or not key:
        raise ValueError("SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 未配置")
    return create_client(url, key)


def is_supabase_admin_configured() -> bool:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (
        (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        or (os.getenv("SUPABASE_KEY") or "").strip()
    )
    return bool(url and key)


def _normalize_trade_date(raw: Any) -> str:
    if isinstance(raw, date):
        return raw.isoformat()
    text = str(raw or "").strip()
    if len(text) >= 10:
        return text[:10]
    return text


def _safe_float(raw: Any) -> float | None:
    try:
        if raw is None:
            return None
        text = str(raw).strip().replace(",", "")
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _format_signed_pct(raw: Any) -> str:
    value = _safe_float(raw)
    if value is None:
        return "--"
    return f"{value:+.2f}%"


def _format_plain(raw: Any, digits: int = 2) -> str:
    value = _safe_float(raw)
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def _benchmark_regime_desc(regime: str) -> str:
    mapping = {
        "RISK_ON": "偏强",
        "NEUTRAL": "中性",
        "RISK_OFF": "偏弱",
        "CRASH": "极弱",
        "BLACK_SWAN": "极端恶劣",
        "UNKNOWN": "待确认",
    }
    return mapping.get(str(regime or "").strip().upper(), "待确认")


def _premarket_regime_desc(regime: str) -> str:
    mapping = {
        "NORMAL": "平稳",
        "RISK_OFF": "转冷",
        "BLACK_SWAN": "急剧恶化",
    }
    return mapping.get(str(regime or "").strip().upper(), "待确认")


def compose_market_banner(row: dict[str, Any] | None) -> dict[str, str]:
    data = dict(row or {})
    trade_date = _normalize_trade_date(data.get("trade_date"))
    benchmark_regime = str(data.get("benchmark_regime", "") or "").strip().upper()
    premarket_regime = str(data.get("premarket_regime", "") or "").strip().upper()
    a50_pct = _safe_float(data.get("a50_pct_chg"))
    vix_pct = _safe_float(data.get("vix_pct_chg"))

    if benchmark_regime in {"CRASH", "BLACK_SWAN"} or (
        premarket_regime == "BLACK_SWAN" and benchmark_regime not in {"RISK_ON"}
    ):
        tone = "恶劣"
    elif premarket_regime in {"BLACK_SWAN", "RISK_OFF"} or benchmark_regime == "RISK_OFF":
        tone = "保守"
    elif benchmark_regime == "NEUTRAL":
        tone = "谨慎"
    elif benchmark_regime == "RISK_ON" and (
        premarket_regime in {"BLACK_SWAN", "RISK_OFF"}
        or (a50_pct is not None and a50_pct < 0)
        or (vix_pct is not None and vix_pct >= 8.0)
    ):
        tone = "谨慎乐观"
    elif benchmark_regime == "RISK_ON":
        tone = "乐观"
    else:
        tone = "谨慎"

    bench_desc = _benchmark_regime_desc(benchmark_regime)
    pre_desc = _premarket_regime_desc(premarket_regime)

    if benchmark_regime == "RISK_ON" and premarket_regime in {"BLACK_SWAN", "RISK_OFF"}:
        title = "亲爱的投资者，最新交易日的大盘偏强，但盘前风险已显著抬升。"
    elif benchmark_regime in {"CRASH", "BLACK_SWAN"}:
        title = "亲爱的投资者，最新交易日市场环境恶劣，防守优先。"
    elif benchmark_regime == "RISK_ON" and premarket_regime == "NORMAL":
        title = "亲爱的投资者，最新交易日的大盘与盘前信号共振偏强。"
    elif benchmark_regime == "NEUTRAL" and premarket_regime in {"BLACK_SWAN", "RISK_OFF"}:
        title = "亲爱的投资者，最新交易日水温中性，但盘前风险需要优先防守。"
    else:
        title = "亲爱的投资者，最新交易日请顺势而为，保持节奏。"

    tone_tail = {
        "恶劣": "市场环境恶劣，先保命，再谈进攻。",
        "保守": "市场当前更适合保守应对，既要乘风而上，也要顺水推舟。",
        "谨慎": "当前更适合耐心观察，等待更清晰的结构确认。",
        "谨慎乐观": "可以顺势，但不宜激进，优先做确定性更高的机会。",
        "乐观": "水温与风险信号配合良好，可以在纪律下积极把握机会。",
    }
    benchmark_text = (
        f"最新交易日（{trade_date}）的大盘水温为 {benchmark_regime or 'UNKNOWN'}（{bench_desc}）"
        if trade_date
        else f"大盘水温为 {benchmark_regime or 'UNKNOWN'}（{bench_desc}）"
    )
    a50_text = f"A50 最新 {_format_plain(data.get('a50_close'))}（{_format_signed_pct(data.get('a50_pct_chg'))}）"
    vix_text = f"VIX {_format_plain(data.get('vix_close'))}（{_format_signed_pct(data.get('vix_pct_chg'))}）"
    risk_text = f"盘前风险信号{pre_desc}，{a50_text}，{vix_text}。"
    tail_text = tone_tail.get(tone, "保持纪律，尊重市场。")

    return {
        "banner_tone": tone,
        "banner_title": title,
        "banner_message": f"{benchmark_text}；{risk_text}{tail_text}",
    }


def _deep_merge_source_jobs(base: Any, patch: Any) -> dict[str, Any]:
    left = dict(base or {}) if isinstance(base, dict) else {}
    right = dict(patch or {}) if isinstance(patch, dict) else {}
    merged = dict(left)
    for key, value in right.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _normalize_row_for_upsert(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if "trade_date" in out:
        out["trade_date"] = _normalize_trade_date(out.get("trade_date"))
    for key in [
        "main_index_close",
        "main_index_ma50",
        "main_index_ma200",
        "main_index_recent3_cum_pct",
        "main_index_today_pct",
        "smallcap_close",
        "smallcap_recent3_cum_pct",
        "a50_close",
        "a50_pct_chg",
        "vix_close",
        "vix_pct_chg",
    ]:
        if key in out:
            out[key] = _safe_float(out.get(key))
    for key in ["a50_value_date", "vix_value_date"]:
        if key in out and out.get(key):
            out[key] = _normalize_trade_date(out.get(key))
    if "premarket_reasons" in out and out.get("premarket_reasons") is None:
        out["premarket_reasons"] = []
    if "source_jobs" in out and not isinstance(out.get("source_jobs"), dict):
        out["source_jobs"] = {}
    return out


def _load_market_signal_by_trade_date(client: Client, trade_date: str) -> dict[str, Any] | None:
    resp = (
        client.table(TABLE_MARKET_SIGNAL_DAILY)
        .select("*")
        .eq("trade_date", trade_date)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    return dict(resp.data[0])


def upsert_market_signal_daily(trade_date: date | str, patch: dict[str, Any]) -> bool:
    if not is_supabase_admin_configured():
        return False
    try:
        client = _get_supabase_admin_client()
        trade_date_text = _normalize_trade_date(trade_date)
        existing = _load_market_signal_by_trade_date(client, trade_date_text) or {}
        merged = dict(existing)
        merged.update(_normalize_row_for_upsert(dict(patch or {})))
        merged["trade_date"] = trade_date_text
        merged["source_jobs"] = _deep_merge_source_jobs(
            existing.get("source_jobs"),
            patch.get("source_jobs") if isinstance(patch, dict) else None,
        )
        merged.update(compose_market_banner(merged))
        merged["updated_at"] = datetime.utcnow().isoformat()
        client.table(TABLE_MARKET_SIGNAL_DAILY).upsert(
            _normalize_row_for_upsert(merged),
            on_conflict="trade_date",
        ).execute()
        return True
    except Exception as e:
        print(f"[supabase_market_signal] upsert_market_signal_daily failed: {e}")
        return False


def load_latest_market_signal_daily(client: Client | None = None) -> dict[str, Any] | None:
    try:
        sb = client
        if sb is None:
            from integrations.supabase_client import get_supabase_client

            sb = get_supabase_client()
        resp = (
            sb.table(TABLE_MARKET_SIGNAL_DAILY)
            .select("*")
            .order("trade_date", desc=True)
            .limit(1)
            .execute()
        )
        if not resp.data:
            return None
        return dict(resp.data[0])
    except Exception:
        return None
