"""Mainline theme engine for A-share funnel candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from core.theme_radar import normalize_theme_name

MAINLINE_BUY_STATUS = "主线买点候选"
MAINLINE_DIVERGENCE_STATUS = "强主线分歧"
MAINLINE_EVENT_REVERSAL_STATUS = "事件主题修复候选"
MAINLINE_OBSERVE_STATUS = "主线观察"
MAINLINE_AVOID_STATUS = "过热不追"
TRADEABLE_MAINLINE_STATUSES = frozenset(
    {MAINLINE_BUY_STATUS, MAINLINE_DIVERGENCE_STATUS, MAINLINE_EVENT_REVERSAL_STATUS}
)
BLOCKING_TIMING_FLAGS = {"鱼尾加速", "放量长上影", "跌破确认支撑", "主题缩量阴跌"}


@dataclass(frozen=True)
class MainlineEngineConfig:
    enabled: bool = True
    max_ai_candidates: int = 3
    min_theme_score: float = 0.55
    min_stock_score: float = 0.60
    min_timing_score: float = 0.55
    allow_l2_bypass: bool = True
    allow_l4_bypass: bool = False
    max_candidates_per_theme: int = 8
    themes: tuple[str, ...] = ()
    core_basket: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class MainlineCandidate:
    code: str
    name: str
    theme: str
    status: str
    entry_type: str
    mainline_score: float
    theme_score: float
    stock_role_score: float
    quality_score: float
    timing_score: float
    l2_passed: bool
    source: str
    reasons: list[str]
    risk_flags: list[str]
    metrics: dict[str, float]


def build_mainline_candidates(
    *,
    l1_passed: list[str],
    l2_passed: list[str],
    concept_map: dict[str, list[str]],
    concept_heat: list[dict[str, Any]],
    theme_radar: dict[str, Any],
    df_map: dict[str, pd.DataFrame],
    financial_map: dict[str, dict],
    name_map: dict[str, str],
    config: MainlineEngineConfig | None = None,
) -> list[dict[str, Any]]:
    cfg = config or MainlineEngineConfig()
    if not cfg.enabled:
        return []
    l1_set = {str(code).strip() for code in l1_passed if str(code).strip()}
    l2_set = {str(code).strip() for code in l2_passed if str(code).strip()}
    theme_scores = _theme_scores(concept_heat, theme_radar, cfg)
    seeds = _mainline_seed_map(l1_set, concept_map, theme_scores, theme_radar, cfg)
    candidates = [
        _candidate_from_seed(code, seed, l2_set, df_map, financial_map, name_map, theme_scores, cfg)
        for code, seed in seeds.items()
        if code in df_map and (cfg.allow_l2_bypass or code in l2_set)
    ]
    return [asdict(item) for item in _rank_candidates([c for c in candidates if c is not None], cfg)]


def mainline_candidate_entries(candidates: list[dict[str, Any]], *, max_count: int) -> list[dict[str, Any]]:
    tradeable = [item for item in candidates if str(item.get("status")) in TRADEABLE_MAINLINE_STATUSES]
    ranked = sorted(tradeable, key=lambda item: (-float(item.get("mainline_score") or 0), str(item.get("code"))))
    rows = ranked if max_count <= 0 else ranked[:max_count]
    return [_candidate_entry(item) for item in rows]


def _mainline_seed_map(
    l1_set: set[str],
    concept_map: dict[str, list[str]],
    theme_scores: dict[str, float],
    theme_radar: dict[str, Any],
    cfg: MainlineEngineConfig,
) -> dict[str, dict[str, Any]]:
    seeds: dict[str, dict[str, Any]] = {}
    _add_core_basket_seeds(seeds, l1_set, cfg)
    _add_radar_seeds(seeds, l1_set, theme_radar, cfg)
    _add_concept_seeds(seeds, l1_set, concept_map, theme_scores, cfg)
    return seeds


def _add_core_basket_seeds(seeds: dict[str, dict[str, Any]], l1_set: set[str], cfg: MainlineEngineConfig) -> None:
    for code, name, theme in cfg.core_basket:
        if code in l1_set:
            seeds.setdefault(code, {"theme": theme, "source": "core_basket", "name": name})


def _add_radar_seeds(
    seeds: dict[str, dict[str, Any]],
    l1_set: set[str],
    theme_radar: dict[str, Any],
    cfg: MainlineEngineConfig,
) -> None:
    for item in theme_radar.get("strategic_candidates") or []:
        code = str(item.get("code", "")).strip()
        theme = _mainline_theme(item.get("theme"), cfg)
        if code in l1_set and theme:
            seeds[code] = {"theme": theme, "source": "theme_radar", "radar": item}


def _add_concept_seeds(
    seeds: dict[str, dict[str, Any]],
    l1_set: set[str],
    concept_map: dict[str, list[str]],
    theme_scores: dict[str, float],
    cfg: MainlineEngineConfig,
) -> None:
    active = {theme for theme, score in theme_scores.items() if score >= 0.40}
    for code, concepts in concept_map.items():
        code_s = str(code).strip()
        if code_s not in l1_set or code_s in seeds:
            continue
        for concept in concepts or []:
            theme = _mainline_theme(concept, cfg)
            if theme and theme in active:
                seeds[code_s] = {"theme": theme, "source": "concept_map"}
                break


def _candidate_from_seed(
    code: str,
    seed: dict[str, Any],
    l2_set: set[str],
    df_map: dict[str, pd.DataFrame],
    financial_map: dict[str, dict],
    name_map: dict[str, str],
    theme_scores: dict[str, float],
    cfg: MainlineEngineConfig,
) -> MainlineCandidate | None:
    metrics = _price_metrics(df_map.get(code))
    if not metrics:
        return None
    theme = str(seed.get("theme") or "")
    radar = seed.get("radar") or {}
    theme_score = _seed_theme_score(seed, theme, theme_scores, radar)
    role_score = _stock_role_score(metrics, radar, seed.get("source") == "core_basket")
    quality_score = _quality_score(_lookup_financial(financial_map, code))
    timing_score, entry_type, risk_flags = _timing_result(metrics)
    mainline_score = _score(theme_score, role_score, quality_score, timing_score)
    status = _status(theme_score, role_score, timing_score, entry_type, risk_flags, cfg)
    return MainlineCandidate(
        code=code,
        name=str(seed.get("name") or name_map.get(code) or radar.get("name") or code),
        theme=theme,
        status=status,
        entry_type=entry_type,
        mainline_score=round(mainline_score, 4),
        theme_score=round(theme_score, 4),
        stock_role_score=round(role_score, 4),
        quality_score=round(quality_score, 4),
        timing_score=round(timing_score, 4),
        l2_passed=code in l2_set,
        source=str(seed.get("source") or "mainline"),
        reasons=_reasons(theme, theme_score, role_score, quality_score, timing_score, entry_type),
        risk_flags=risk_flags,
        metrics=metrics,
    )


def _rank_candidates(candidates: list[MainlineCandidate], cfg: MainlineEngineConfig) -> list[MainlineCandidate]:
    status_rank = {
        MAINLINE_BUY_STATUS: 0,
        MAINLINE_DIVERGENCE_STATUS: 1,
        MAINLINE_EVENT_REVERSAL_STATUS: 2,
        MAINLINE_OBSERVE_STATUS: 3,
        MAINLINE_AVOID_STATUS: 4,
    }
    ranked = sorted(candidates, key=lambda item: (status_rank.get(item.status, 9), -item.mainline_score, item.code))
    buckets: dict[str, int] = {}
    out: list[MainlineCandidate] = []
    for item in ranked:
        count = buckets.get(item.theme, 0)
        if count < cfg.max_candidates_per_theme or item.source == "core_basket":
            out.append(item)
            buckets[item.theme] = count + 1
    return out


def _seed_theme_score(seed: dict[str, Any], theme: str, theme_scores: dict[str, float], radar: dict[str, Any]) -> float:
    score = max(float(theme_scores.get(theme, 0.0)), _safe_float(radar.get("theme_score")))
    return max(score, 0.55) if seed.get("source") == "core_basket" else score


def _theme_scores(
    concept_heat: list[dict[str, Any]],
    theme_radar: dict[str, Any],
    cfg: MainlineEngineConfig,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for item in theme_radar.get("themes") or []:
        theme = _mainline_theme(item.get("theme"), cfg)
        if theme:
            scores[theme] = max(scores.get(theme, 0.0), _safe_float(item.get("score")))
    for item in theme_radar.get("strategic_candidates") or []:
        theme = _mainline_theme(item.get("theme"), cfg)
        if theme:
            scores[theme] = max(scores.get(theme, 0.0), _safe_float(item.get("theme_score")))
    for rank, item in enumerate(concept_heat or [], start=1):
        theme = _mainline_theme(item.get("name"), cfg)
        if theme:
            scores[theme] = max(scores.get(theme, 0.0), _heat_score(item, rank))
    return scores


def _mainline_theme(raw: Any, cfg: MainlineEngineConfig) -> str:
    theme = normalize_theme_name(str(raw or ""))
    return theme if theme and (not cfg.themes or theme in set(cfg.themes)) else ""


def _price_metrics(df: pd.DataFrame | None) -> dict[str, float]:
    if df is None or df.empty or "close" not in df.columns:
        return {}
    ordered = df.sort_values("date") if "date" in df.columns else df
    close = pd.to_numeric(ordered["close"], errors="coerce").dropna()
    if len(close) < 60:
        return {}
    volume = _numeric_series(ordered, "volume")
    amount = _numeric_series(ordered, "amount")
    high = _numeric_series(ordered, "high")
    low = _numeric_series(ordered, "low")
    open_ = _numeric_series(ordered, "open")
    last = float(close.iloc[-1])
    ma20 = float(close.tail(20).mean())
    ma50 = float(close.tail(50).mean())
    high20 = float(high.tail(20).max()) if not high.empty else float(close.tail(20).max())
    low20 = float(low.tail(20).min()) if not low.empty else float(close.tail(20).min())
    return {
        "ret5": _ret_pct(close, 5),
        "ret20": _ret_pct(close, 20),
        "ret60": _ret_pct(close, 60),
        "ret120": _ret_pct(close, 120),
        "dist_ma20": (last / ma20 - 1.0) * 100.0 if ma20 > 0 else 0.0,
        "dist_ma50": (last / ma50 - 1.0) * 100.0 if ma50 > 0 else 0.0,
        "drawdown60": _drawdown_pct(close, 60),
        "close_pos20": _range_pos(last, low20, high20),
        "close_pos_day": _day_close_pos(ordered, high, low),
        "upper_shadow_pct": _upper_shadow_pct(ordered, open_, high, close),
        "vol_ratio_5_20": _vol_ratio(volume),
        "amount20_wan": _amount20_wan(amount),
    }


def _timing_result(metrics: dict[str, float]) -> tuple[float, str, list[str]]:
    risk_flags = _timing_risks(metrics)
    score = _timing_score(metrics, risk_flags)
    entries = _entry_types(metrics, risk_flags)
    return score, " + ".join(entries), risk_flags


def _timing_risks(metrics: dict[str, float]) -> list[str]:
    risks: list[str] = []
    if _fish_tail_risk(metrics):
        risks.append("鱼尾加速")
    elif metrics["dist_ma20"] > 16 or metrics["ret20"] > 42:
        risks.append("高位抱团")
    if metrics["upper_shadow_pct"] > 5 and metrics["vol_ratio_5_20"] > 1.8 and metrics["close_pos_day"] < 0.45:
        risks.append("放量长上影")
    if metrics["dist_ma20"] < -5 or metrics["dist_ma50"] < -8:
        risks.append("跌破确认支撑")
    if metrics["ret20"] < -8 and metrics["vol_ratio_5_20"] < 0.9:
        risks.append("主题缩量阴跌")
    return risks


def _entry_types(metrics: dict[str, float], risk_flags: list[str]) -> list[str]:
    entries: list[str] = []
    if _event_reversal_entry_ok(metrics, risk_flags):
        entries.append("事件主题低位修复")
    if any(flag in risk_flags for flag in BLOCKING_TIMING_FLAGS if flag != "跌破确认支撑"):
        return entries
    if "跌破确认支撑" in risk_flags and not entries:
        return []
    if -2 <= metrics["dist_ma20"] <= 8 and metrics["dist_ma50"] >= -2 and metrics["ret60"] >= 8:
        entries.append("主线回踩MA20")
    if metrics["close_pos20"] >= 0.86 and 4 <= metrics["ret20"] <= 36 and 0.75 <= metrics["vol_ratio_5_20"] <= 2.2:
        entries.append("主线平台再突破")
    if metrics["dist_ma20"] >= -1 and metrics["vol_ratio_5_20"] <= 0.90 and -6 <= metrics["ret5"] <= 6:
        entries.append("主线缩量强承接")
    entries.extend(_extended_mainline_entries(metrics, risk_flags))
    return entries


def _extended_mainline_entries(metrics: dict[str, float], risk_flags: list[str]) -> list[str]:
    if "高位抱团" not in risk_flags or not _high_mainline_support(metrics):
        return []
    entries: list[str] = []
    if -8 <= metrics["ret5"] <= 12 and metrics["vol_ratio_5_20"] <= 1.45:
        entries.append("主线高位横盘承接")
    if metrics["close_pos20"] >= 0.78 and metrics["ret20"] <= 65 and metrics["close_pos_day"] >= 0.55:
        entries.append("主线分歧转强")
    return entries


def _timing_score(metrics: dict[str, float], risk_flags: list[str]) -> float:
    trend = 0.25 * float(metrics["dist_ma20"] >= -2) + 0.20 * float(metrics["dist_ma50"] >= -3)
    strength = 0.20 * _clamp((metrics["ret60"] - 5) / 45) + 0.15 * _clamp(metrics["close_pos20"])
    distance = 0.10 * _clamp(1.0 - max(metrics["dist_ma20"] - 8, 0.0) / 14.0)
    volume = 0.10 * _clamp(1.0 - max(metrics["vol_ratio_5_20"] - 1.6, 0.0) / 1.4)
    extension = 0.12 * float(_high_mainline_support(metrics))
    event_reversal = 0.16 * float(_event_reversal_entry_ok(metrics, risk_flags))
    return _clamp(trend + strength + distance + volume + extension + event_reversal)


def _event_reversal_entry_ok(metrics: dict[str, float], risk_flags: list[str]) -> bool:
    if "鱼尾加速" in risk_flags or "放量长上影" in risk_flags:
        return False
    return (
        metrics["amount20_wan"] >= 12000.0
        and -28.0 <= metrics["ret20"] <= 18.0
        and -45.0 <= metrics["ret60"] <= 55.0
        and -16.0 <= metrics["dist_ma20"] <= 8.0
        and -28.0 <= metrics["dist_ma50"] <= 12.0
        and metrics["close_pos20"] >= 0.22
        and 0.60 <= metrics["vol_ratio_5_20"] <= 2.60
    )


def _fish_tail_risk(metrics: dict[str, float]) -> bool:
    return (
        metrics["dist_ma20"] > 30
        or metrics["ret20"] > 68
        or (metrics["ret20"] > 50 and metrics["vol_ratio_5_20"] > 2.0)
        or (metrics["upper_shadow_pct"] > 5 and metrics["vol_ratio_5_20"] > 1.8 and metrics["close_pos_day"] < 0.45)
    )


def _high_mainline_support(metrics: dict[str, float]) -> bool:
    return (
        metrics["ret60"] >= 25
        and metrics["dist_ma50"] >= 5
        and metrics["close_pos20"] >= 0.55
        and metrics["drawdown60"] <= 18
        and metrics["vol_ratio_5_20"] <= 2.0
    )


def _stock_role_score(metrics: dict[str, float], radar: dict[str, Any], is_core: bool) -> float:
    radar_score = _safe_float(radar.get("stock_score"))
    absolute_score = (
        0.30 * _clamp((metrics["ret60"] + 5.0) / 45.0)
        + 0.25 * _clamp((metrics["ret120"] + 10.0) / 80.0)
        + 0.20 * _clamp(1.0 - metrics["drawdown60"] / 24.0)
        + 0.15 * _clamp(metrics["close_pos20"])
        + 0.10 * float(metrics["dist_ma50"] >= 0)
    )
    return _clamp(max(radar_score, absolute_score) + (0.10 if is_core else 0.0))


def _quality_score(metrics: dict | None) -> float:
    if not metrics:
        return 0.55
    parts = [
        _metric_score(metrics, ("roe", "roe_weighted", "roe_diluted"), 0.0, 14.0, reverse=False),
        _metric_score(metrics, ("net_income_yoy", "netprofit_yoy"), -15.0, 35.0, reverse=False),
        _metric_score(metrics, ("revenue_yoy", "or_yoy"), -10.0, 30.0, reverse=False),
        _metric_score(metrics, ("gross_margin", "grossprofit_margin"), 12.0, 40.0, reverse=False),
        _metric_score(metrics, ("debt_to_asset_ratio", "debt_to_assets", "debt_ratio"), 85.0, 45.0, reverse=True),
        _metric_score(metrics, ("operating_cash_to_revenue", "ocf_to_or"), -5.0, 12.0, reverse=False),
    ]
    valid = [x for x in parts if x is not None]
    return round(sum(valid) / len(valid), 4) if valid else 0.55


def _candidate_entry(item: dict[str, Any]) -> dict[str, Any]:
    score = round(float(item.get("mainline_score") or 0.0) * 100.0, 2)
    status = str(item.get("status") or MAINLINE_BUY_STATUS)
    return {
        "code": item["code"],
        "track": "trend",
        "signal_key": "mainline",
        "entry_type": str(item.get("entry_type") or "mainline"),
        "lane": "mainline",
        "score": score,
        "opportunity": f"主线核心票: {item.get('theme')}",
        "timing": str(item.get("entry_type") or ""),
        "risk": " / ".join([status, *list(item.get("risk_flags") or [])]) or "尾盘仍需二次确认",
        "state": "Mainline",
        "reasons": list(item.get("reasons") or [])[:5],
    }


def _reasons(theme: str, theme_score: float, role_score: float, quality: float, timing: float, entry: str) -> list[str]:
    return [
        f"主题:{theme}({theme_score:.2f})",
        f"核心度:{role_score:.2f}",
        f"质量:{quality:.2f}",
        f"时机:{timing:.2f}",
        entry or "等待买点确认",
    ]


def _status(
    theme_score: float,
    role_score: float,
    timing_score: float,
    entry_type: str,
    risk_flags: list[str],
    cfg: MainlineEngineConfig,
) -> str:
    if "鱼尾加速" in risk_flags:
        return MAINLINE_AVOID_STATUS
    if _high_divergence_is_tradeable(theme_score, role_score, timing_score, entry_type, risk_flags, cfg):
        return MAINLINE_DIVERGENCE_STATUS
    if _event_reversal_is_tradeable(theme_score, timing_score, entry_type, risk_flags, cfg):
        return MAINLINE_EVENT_REVERSAL_STATUS
    if (
        theme_score >= cfg.min_theme_score
        and role_score >= cfg.min_stock_score
        and timing_score >= cfg.min_timing_score
        and entry_type
    ):
        return MAINLINE_BUY_STATUS
    return MAINLINE_OBSERVE_STATUS


def _event_reversal_is_tradeable(
    theme_score: float,
    timing_score: float,
    entry_type: str,
    risk_flags: list[str],
    cfg: MainlineEngineConfig,
) -> bool:
    return (
        "事件主题低位修复" in entry_type
        and theme_score >= max(cfg.min_theme_score - 0.05, 0.45)
        and timing_score >= max(cfg.min_timing_score * 0.45, 0.24)
        and not {"鱼尾加速", "放量长上影"} & set(risk_flags)
    )


def _high_divergence_is_tradeable(
    theme_score: float,
    role_score: float,
    timing_score: float,
    entry_type: str,
    risk_flags: list[str],
    cfg: MainlineEngineConfig,
) -> bool:
    return (
        "高位抱团" in risk_flags
        and theme_score >= cfg.min_theme_score
        and role_score >= cfg.min_stock_score
        and timing_score >= cfg.min_timing_score * 0.8
        and bool(entry_type)
    )


def _metric_score(metrics: dict, keys: tuple[str, ...], weak: float, strong: float, *, reverse: bool) -> float | None:
    value = next(
        (_safe_float(metrics.get(key), None) for key in keys if _safe_float(metrics.get(key), None) is not None), None
    )
    if value is None:
        return None
    if reverse:
        return _clamp((weak - value) / (weak - strong))
    return _clamp((value - weak) / (strong - weak))


def _lookup_financial(financial_map: dict[str, dict], code: str) -> dict | None:
    suffix = ".SH" if code.startswith(("6", "9")) else ".SZ"
    return financial_map.get(code) or financial_map.get(f"{code}{suffix}")


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


def _ret_pct(close: pd.Series, lookback: int) -> float:
    if len(close) <= lookback:
        return 0.0
    start = float(close.iloc[-lookback - 1])
    return 0.0 if start <= 0 else (float(close.iloc[-1]) / start - 1.0) * 100.0


def _drawdown_pct(close: pd.Series, lookback: int) -> float:
    recent = close.tail(max(lookback, 1))
    high = float(recent.max()) if not recent.empty else 0.0
    return 0.0 if high <= 0 else (float(recent.iloc[-1]) / high - 1.0) * -100.0


def _range_pos(value: float, low: float, high: float) -> float:
    return 0.5 if high <= low else _clamp((value - low) / (high - low))


def _day_close_pos(df: pd.DataFrame, high: pd.Series, low: pd.Series) -> float:
    if high.empty or low.empty:
        return 0.5
    return _range_pos(float(df["close"].iloc[-1]), float(low.iloc[-1]), float(high.iloc[-1]))


def _upper_shadow_pct(df: pd.DataFrame, open_: pd.Series, high: pd.Series, close: pd.Series) -> float:
    if high.empty or close.empty:
        return 0.0
    base = float(close.iloc[-1])
    body_top = max(float(close.iloc[-1]), float(open_.iloc[-1]) if not open_.empty else base)
    return 0.0 if base <= 0 else max(float(high.iloc[-1]) - body_top, 0.0) / base * 100.0


def _vol_ratio(volume: pd.Series) -> float:
    if len(volume) < 20:
        return 1.0
    base = float(volume.tail(20).mean())
    return 1.0 if base <= 0 else float(volume.tail(5).mean()) / base


def _amount20_wan(amount: pd.Series) -> float:
    if len(amount) < 20:
        return 0.0
    return float(amount.tail(20).mean()) / 10000.0


def _score(theme: float, role: float, quality: float, timing: float) -> float:
    return _clamp(0.30 * theme + 0.25 * role + 0.20 * quality + 0.25 * timing)


def _heat_score(item: dict[str, Any], rank: int) -> float:
    pct = _safe_float(item.get("pct"))
    flow = max(_safe_float(item.get("net_inflow")) / 1e8, 0.0)
    return _clamp(0.45 * ((pct + 2.0) / 10.0) + 0.35 * min(flow / 8.0, 1.0) + 0.20 * (1.0 - rank / 40.0))


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(result) else result


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
