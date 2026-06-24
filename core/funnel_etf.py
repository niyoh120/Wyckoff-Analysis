"""ETF enhancement ranking and report helpers for the funnel."""

from __future__ import annotations

import pandas as pd

from core.candidate_ranker import calc_close_return_pct
from core.funnel_format import fmt_pct, fmt_ratio
from core.wyckoff_engine import FunnelConfig


def build_etf_funnel_config(base_cfg: FunnelConfig) -> FunnelConfig:
    cfg = FunnelConfig(trading_days=base_cfg.trading_days)
    cfg.require_cn_main_or_chinext = False
    cfg.min_market_cap_yi = 0.0
    cfg.min_avg_amount_wan = 50.0
    cfg.enable_rs_filter = False
    cfg.enable_rps_filter = False
    cfg.enable_rs_divergence_channel = False
    cfg.require_bench_latest_alignment = False
    cfg.sos_pct_min = 3.5
    cfg.sos_vol_ratio = 2.0
    cfg.spring_vol_ratio = 1.0
    cfg.evr_min_turnover = 0.3
    cfg.evr_max_rise = 2.0
    return cfg


def rank_etf_candidates(
    l2_passed: list[str],
    df_map: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
    channel_map: dict[str, str],
) -> list[dict]:
    rows = [
        row
        for code in l2_passed
        if (row := _candidate_row(code, df_map.get(code), sector_map, channel_map)) is not None
    ]
    rows.sort(key=lambda row: float(row.get("score", 0.0) or 0.0), reverse=True)
    return rows


def etf_metrics(syms, df_map, l2_passed, sector_map, candidates=None) -> dict:
    return {
        "pool": len(syms),
        "fetched": len(df_map),
        "l2_passed": len(l2_passed),
        "strong_candidates": len(candidates or []),
        "boosted_sectors": sorted({sector_map.get(s, "") for s in l2_passed} - {""}),
    }


def append_etf_section(lines: list[str], metrics: dict, candidates: list[dict], *, display_limit: int = 0) -> None:
    if not metrics and not candidates:
        return
    pool = int(metrics.get("pool", 0) or 0)
    fetched = int(metrics.get("fetched", 0) or 0)
    l2_passed = int(metrics.get("l2_passed", 0) or 0)
    lines.append(f"**ETF强势池**: 池{pool} → 拉取{fetched} → L2强势{l2_passed}")
    if not candidates:
        return
    display = candidates if display_limit <= 0 else candidates[:display_limit]
    lines.append(f"**【📈 强势ETF】{len(candidates)} 只**")
    lines.extend(_render_etf_row(row) for row in display)
    omitted = len(candidates) - len(display)
    if omitted > 0:
        lines.append(f"  ... 另 {omitted} 只略")


def _candidate_row(
    code: str,
    df: pd.DataFrame | None,
    sector_map: dict[str, str],
    channel_map: dict[str, str],
) -> dict | None:
    if df is None or df.empty or "close" not in df.columns:
        return None
    s = df.sort_values("date") if "date" in df.columns else df
    close = pd.to_numeric(s["close"], errors="coerce")
    ret3, ret5, ret20 = (
        calc_close_return_pct(close, 3),
        calc_close_return_pct(close, 5),
        calc_close_return_pct(close, 20),
    )
    vol_ratio = _latest_volume_ratio(s)
    channel = str(channel_map.get(code, "") or "").strip()
    score = _etf_score(ret3, ret5, ret20, vol_ratio, channel)
    return {
        "code": code,
        "name": _etf_display_name(code, sector_map),
        "sector": str(sector_map.get(code, "") or ""),
        "channel": channel,
        "ret3": ret3,
        "ret5": ret5,
        "ret20": ret20,
        "vol_ratio": vol_ratio,
        "score": score,
    }


def _etf_score(
    ret3: float | None, ret5: float | None, ret20: float | None, vol_ratio: float | None, channel: str
) -> float:
    channel_bonus = 3.0 if "主升" in channel or "点火" in channel else 0.0
    return (
        max(ret20 or 0.0, -10.0) * 0.35
        + max(ret5 or 0.0, -5.0) * 0.75
        + max(ret3 or 0.0, -3.0) * 1.1
        + min(max(vol_ratio or 1.0, 0.0), 3.0) * 2.0
        + channel_bonus
    )


def _etf_display_name(code: str, sector_map: dict[str, str]) -> str:
    tag = str(sector_map.get(code, "") or "").strip()
    if not tag:
        return code
    if tag.upper().endswith("ETF") or tag.endswith("基金"):
        return tag
    return f"{tag}ETF"


def _latest_volume_ratio(df: pd.DataFrame) -> float | None:
    if df is None or df.empty or "volume" not in df.columns:
        return None
    volume = pd.to_numeric(df["volume"], errors="coerce")
    vol_ma20 = volume.rolling(20, min_periods=5).mean()
    latest = volume.dropna()
    ma_latest = vol_ma20.dropna()
    if latest.empty or ma_latest.empty:
        return None
    base = float(ma_latest.iloc[-1])
    return None if base <= 0 else float(latest.iloc[-1]) / base


def _render_etf_row(row: dict) -> str:
    channel = str(row.get("channel", "") or "").replace("通道", "")
    parts = [
        f"3日{fmt_pct(row.get('ret3'))}",
        f"20日{fmt_pct(row.get('ret20'))}",
        f"量{fmt_ratio(row.get('vol_ratio'))}",
    ]
    if channel:
        parts.append(channel)
    return f"  {row.get('code')} {row.get('name')}  {float(row.get('score', 0.0) or 0.0):.2f}  {' | '.join(parts)}"
