"""Long-horizon theme radar for strategic watchlists."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import log1p
from statistics import median
from typing import Any

import pandas as pd

from core.concept_filters import is_actionable_theme_name

THEME_ALIASES: dict[str, tuple[str, ...]] = {
    "芯片半导体": ("芯片", "半导体", "集成电路", "先进封装", "存储", "光刻胶", "第三代半导体", "semiconductor", "chip"),
    "AI算力": ("人工智能", "AI应用", "大模型", "算力", "数据中心", "服务器", "液冷", "PCB", "data center", "server"),
    "光模块": (
        "光模块",
        "光通信",
        "800G",
        "1.6T",
        "硅光",
        "CPO",
        "铜缆高速连接",
        "高速铜缆",
        "optical module",
        "silicon photonics",
    ),
    "机器人": ("机器人", "人形机器人", "减速器", "伺服", "机器视觉", "传感器", "robot", "robotics", "actuator"),
    "有色资源": (
        "稀土",
        "小金属",
        "铜",
        "铝",
        "钨",
        "锑",
        "钼",
        "黄金",
        "锂",
        "钴",
        "镍",
        "rare earth",
        "copper",
        "tungsten",
    ),
    "新能源": ("新能源", "储能", "光伏", "锂电", "固态电池", "风电", "电网设备"),
    "低空经济": ("低空经济", "无人机", "eVTOL", "飞行汽车", "通航"),
}


@dataclass(frozen=True)
class ThemeRadarConfig:
    top_themes: int = 12
    max_candidates_per_theme: int = 8
    min_theme_score: float = 0.45
    min_stock_score: float = 0.45


@dataclass(frozen=True)
class ThemeScore:
    theme: str
    score: float
    state: str
    heat_score: float
    leader_score: float
    structure_score: float
    breadth_score: float
    persistence_score: float
    catalyst_score: float
    crowding_score: float
    member_count: int
    leader_count: int
    evidence: list[str]


@dataclass(frozen=True)
class StrategicCandidate:
    code: str
    name: str
    theme: str
    theme_score: float
    stock_score: float
    leader_score: float
    theme_rank: int
    ret60: float
    ret120: float
    ret250: float
    near_high_120d: bool
    breakout_age_days: int
    state: str
    reasons: list[str]


def normalize_theme_name(raw: str, aliases: dict[str, tuple[str, ...]] | None = None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    lower_text = text.lower()
    for theme, keys in (aliases or THEME_ALIASES).items():
        if theme in text or any(key and key.lower() in lower_text for key in keys):
            return theme
    return text


def infer_event_themes(event: dict[str, Any], aliases: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    text = " ".join(str(event.get(k, "") or "") for k in ("title", "summary", "content", "tags"))
    lower_text = text.lower()
    themes = [
        theme
        for theme, keys in (aliases or THEME_ALIASES).items()
        if theme in text or any(key and key.lower() in lower_text for key in keys)
    ]
    return sorted(set(themes))


def build_theme_radar_snapshot(
    *,
    trade_date: str,
    concept_heat: list[dict[str, Any]],
    concept_history: dict[str, dict] | None,
    concept_map: dict[str, list[str]],
    sector_map: dict[str, str],
    df_map: dict[str, pd.DataFrame],
    events: list[dict[str, Any]] | None = None,
    name_map: dict[str, str] | None = None,
    config: ThemeRadarConfig | None = None,
) -> dict[str, Any]:
    cfg = config or ThemeRadarConfig()
    features = _stock_features(df_map)
    heat = _heat_by_theme(concept_heat)
    history = _history_by_theme(concept_history or {})
    event_map = _events_by_theme(events or [])
    themes = _theme_universe(heat, history, event_map, concept_map, sector_map)
    scores = [_score_theme(theme, heat, history, event_map, concept_map, sector_map, features) for theme in themes]
    ranked = sorted(scores, key=lambda item: item.score, reverse=True)[: cfg.top_themes]
    candidates = _build_candidates(ranked, concept_map, sector_map, features, name_map or {}, cfg)
    return {
        "trade_date": trade_date,
        "themes": [asdict(item) for item in ranked if item.score >= cfg.min_theme_score],
        "strategic_candidates": [asdict(item) for item in candidates],
    }


def summarize_theme_radar(snapshot: dict[str, Any], limit: int = 5) -> str:
    themes = list(snapshot.get("themes") or [])[:limit]
    if not themes:
        return "无明确中长线主线"
    return "；".join(f"{x['theme']} {x['score']:.2f}/{x['state']}" for x in themes)


def _stock_features(df_map: dict[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    rows = {code: _raw_stock_metrics(df) for code, df in df_map.items() if df is not None and not df.empty}
    rps60 = _rank_metric(rows, "ret60")
    rps120 = _rank_metric(rows, "ret120")
    rps250 = _rank_metric(rows, "ret250")
    for code, row in rows.items():
        row["rps60"] = rps60.get(code, 0.0)
        row["rps120"] = rps120.get(code, 0.0)
        row["rps250"] = rps250.get(code, 0.0)
        row["structure_score"] = _stock_structure_score(row)
        row["leader_score"] = _stock_leader_score(row)
    return rows


def _raw_stock_metrics(df: pd.DataFrame) -> dict[str, Any]:
    ordered = df.sort_values("date") if "date" in df.columns else df
    close_raw = ordered["close"] if "close" in ordered.columns else pd.Series(dtype=float)
    close = pd.to_numeric(close_raw, errors="coerce").dropna()
    return {
        "ret20": _ret_pct(close, 20),
        "ret60": _ret_pct(close, 60),
        "ret120": _ret_pct(close, 120),
        "ret250": _ret_pct(close, 250),
        "above_ma60": _above_ma(close, 60),
        "above_ma120": _above_ma(close, 120),
        "above_ma200": _above_ma(close, 200),
        "drawdown120": _drawdown_pct(close, 120),
        "near_high_120d": _near_high(close, 120),
        "breakout_age_days": _days_since_high(close, 120),
    }


def _rank_metric(rows: dict[str, dict[str, Any]], field: str) -> dict[str, float]:
    values = [(code, _as_float(row.get(field))) for code, row in rows.items()]
    values = [(code, value) for code, value in values if value is not None]
    if not values:
        return {}
    ordered = sorted(values, key=lambda item: item[1])
    denom = max(len(ordered) - 1, 1)
    return {code: idx / denom for idx, (code, _) in enumerate(ordered)}


def _stock_structure_score(row: dict[str, Any]) -> float:
    ma_score = sum(float(row.get(k, 0.0) or 0.0) for k in ("above_ma60", "above_ma120", "above_ma200")) / 3
    drawdown = _clamp(1.0 - max(float(row.get("drawdown120") or 0.0), 0.0) / 35.0)
    return _clamp(0.35 * row.get("rps120", 0.0) + 0.25 * row.get("rps250", 0.0) + 0.25 * ma_score + 0.15 * drawdown)


def _stock_leader_score(row: dict[str, Any]) -> float:
    rps_score = (
        0.20 * float(row.get("rps60", 0.0) or 0.0)
        + 0.35 * float(row.get("rps120", 0.0) or 0.0)
        + 0.45 * float(row.get("rps250", 0.0) or 0.0)
    )
    ret60 = _clamp((float(row.get("ret60") or 0.0) - 20.0) / 60.0)
    ret120 = _clamp((float(row.get("ret120") or 0.0) - 35.0) / 100.0)
    ret250 = _clamp((float(row.get("ret250") or 0.0) - 50.0) / 160.0)
    absolute_score = 0.25 * ret60 + 0.45 * ret120 + 0.30 * ret250
    near_high = float(row.get("near_high_120d", 0.0) or 0.0)
    structure = float(row.get("structure_score", 0.0) or 0.0)
    return _clamp(0.45 * rps_score + 0.25 * absolute_score + 0.15 * near_high + 0.15 * structure)


def _heat_by_theme(concept_heat: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    heat: dict[str, dict[str, Any]] = {}
    for rank, item in enumerate(concept_heat or [], start=1):
        theme = normalize_theme_name(str(item.get("name", "")))
        if not theme or not is_actionable_theme_name(theme):
            continue
        bucket = heat.setdefault(theme, {"score": 0.0, "concepts": [], "pct": 0.0, "inflow": 0.0})
        score = _heat_item_score(item, rank)
        bucket["score"] = max(float(bucket["score"]), score)
        bucket["pct"] = max(float(bucket["pct"]), _as_float(item.get("pct")) or 0.0)
        bucket["inflow"] += _as_float(item.get("net_inflow")) or 0.0
        bucket["concepts"].append(str(item.get("name", "")))
    return heat


def _heat_item_score(item: dict[str, Any], rank: int) -> float:
    pct_score = _clamp(((_as_float(item.get("pct")) or 0.0) + 2.0) / 9.0)
    inflow_yi = max((_as_float(item.get("net_inflow")) or 0.0) / 1e8, 0.0)
    flow_score = _clamp(log1p(inflow_yi) / 3.0)
    rank_score = _clamp(1.0 - (rank - 1) / 30.0)
    return 0.35 * pct_score + 0.40 * flow_score + 0.25 * rank_score


def _history_by_theme(history: dict[str, dict]) -> dict[str, dict[str, Any]]:
    dates = sorted(history.keys(), reverse=True)
    if not dates:
        return {}
    latest = _themes_for_day(history.get(dates[0], {}))
    result: dict[str, dict[str, Any]] = {}
    for theme in latest:
        streak = _theme_streak(theme, dates, history)
        appearances = sum(1 for d in dates[:10] if theme in _themes_for_day(history.get(d, {})))
        result[theme] = {"streak": streak, "score": _clamp(0.65 * streak / 5.0 + 0.35 * appearances / 10.0)}
    return result


def _themes_for_day(day: dict[str, Any]) -> set[str]:
    return {theme for name in day.keys() if (theme := normalize_theme_name(name)) and is_actionable_theme_name(theme)}


def _theme_streak(theme: str, dates: list[str], history: dict[str, dict]) -> int:
    streak = 0
    for trade_date in dates:
        if theme not in _themes_for_day(history.get(trade_date, {})):
            break
        streak += 1
    return streak


def _events_by_theme(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        themes = event.get("themes") or infer_event_themes(event)
        for theme in themes:
            normalized = normalize_theme_name(str(theme))
            if is_actionable_theme_name(normalized):
                grouped.setdefault(normalized, []).append(event)
    return grouped


def _theme_universe(*parts: Any) -> list[str]:
    themes: set[str] = set()
    for part in parts[:3]:
        themes.update(str(k) for k in part.keys() if str(k).strip())
    concept_map = parts[3] if len(parts) > 3 else {}
    sector_map = parts[4] if len(parts) > 4 else {}
    for concepts in concept_map.values():
        themes.update(normalize_theme_name(c) for c in concepts or [])
    themes.update(normalize_theme_name(v) for v in sector_map.values())
    return sorted(t for t in themes if t and is_actionable_theme_name(t))


def _score_theme(
    theme: str,
    heat: dict[str, dict[str, Any]],
    history: dict[str, dict[str, Any]],
    events: dict[str, list[dict[str, Any]]],
    concept_map: dict[str, list[str]],
    sector_map: dict[str, str],
    features: dict[str, dict[str, Any]],
) -> ThemeScore:
    market = _theme_market_metrics(_theme_members(theme, concept_map, sector_map), features)
    heat_score = float((heat.get(theme) or {}).get("score") or 0.0)
    persistence = float((history.get(theme) or {}).get("score") or 0.0)
    catalyst = _catalyst_score(events.get(theme, []))
    crowding = _crowding_score(market, heat.get(theme) or {})
    score = _clamp(
        0.24 * market["structure_score"]
        + 0.22 * market["leader_score"]
        + 0.18 * market["breadth_score"]
        + 0.16 * persistence
        + 0.10 * catalyst
        + 0.10 * heat_score
        - 0.08 * crowding
    )
    return ThemeScore(
        theme=theme,
        score=round(score, 4),
        state=_theme_state(score, persistence, crowding, market["leader_score"]),
        heat_score=round(heat_score, 4),
        leader_score=round(market["leader_score"], 4),
        structure_score=round(market["structure_score"], 4),
        breadth_score=round(market["breadth_score"], 4),
        persistence_score=round(persistence, 4),
        catalyst_score=round(catalyst, 4),
        crowding_score=round(crowding, 4),
        member_count=int(market["member_count"]),
        leader_count=int(market["leader_count"]),
        evidence=_theme_evidence(theme, heat, history, events),
    )


def _theme_members(theme: str, concept_map: dict[str, list[str]], sector_map: dict[str, str]) -> list[str]:
    members: set[str] = set()
    for code, concepts in concept_map.items():
        if any(normalize_theme_name(c) == theme for c in concepts or []):
            members.add(str(code))
    for code, sector in sector_map.items():
        if normalize_theme_name(str(sector)) == theme:
            members.add(str(code))
    return sorted(members)


def _theme_market_metrics(members: list[str], features: dict[str, dict[str, Any]]) -> dict[str, float]:
    rows = [features[code] for code in members if code in features]
    if not rows:
        return {
            "member_count": 0,
            "leader_count": 0,
            "leader_score": 0.0,
            "structure_score": 0.0,
            "breadth_score": 0.0,
            "ret20": 0.0,
        }
    structures = sorted((float(row["structure_score"]) for row in rows), reverse=True)[:20]
    leaders = sorted((float(row["leader_score"]) for row in rows), reverse=True)[:20]
    breadth = [_breadth_unit(row) for row in rows]
    ret20_values = [_as_float(row.get("ret20")) or 0.0 for row in rows]
    return {
        "member_count": float(len(rows)),
        "leader_count": float(sum(1 for row in rows if float(row.get("leader_score", 0.0) or 0.0) >= 0.70)),
        "leader_score": float(median(leaders)),
        "structure_score": float(median(structures)),
        "breadth_score": float(sum(breadth) / len(breadth)),
        "ret20": float(median(ret20_values)),
    }


def _breadth_unit(row: dict[str, Any]) -> float:
    ma = sum(float(row.get(k, 0.0) or 0.0) for k in ("above_ma60", "above_ma120", "above_ma200")) / 3
    trend = 1.0 if (_as_float(row.get("ret60")) or 0.0) > 0 else 0.0
    return 0.70 * ma + 0.30 * trend


def _catalyst_score(events: list[dict[str, Any]]) -> float:
    if not events:
        return 0.0
    sources = {str(e.get("source", "") or e.get("domain", "")).strip() for e in events}
    return _clamp(0.55 * min(len(events), 6) / 6.0 + 0.45 * min(len(sources), 4) / 4.0)


def _crowding_score(market: dict[str, float], heat: dict[str, Any]) -> float:
    ret20_score = _clamp((float(market.get("ret20", 0.0)) - 35.0) / 35.0)
    pct_score = _clamp((float(heat.get("pct", 0.0) or 0.0) - 7.0) / 6.0)
    return max(ret20_score, pct_score)


def _theme_state(score: float, persistence: float, crowding: float, leader_score: float) -> str:
    if score >= 0.70 and crowding >= 0.65:
        return "overheated"
    if score >= 0.75 and leader_score >= 0.65:
        return "extension"
    if score >= 0.65 and (persistence >= 0.35 or leader_score >= 0.65):
        return "confirmed"
    if score >= 0.45:
        return "observe"
    return "decay"


def _theme_evidence(
    theme: str,
    heat: dict[str, dict[str, Any]],
    history: dict[str, dict[str, Any]],
    events: dict[str, list[dict[str, Any]]],
) -> list[str]:
    evidence: list[str] = []
    if theme in heat:
        evidence.append("heat:" + ",".join((heat[theme].get("concepts") or [])[:3]))
    if theme in history:
        evidence.append(f"streak:{int(history[theme].get('streak') or 0)}")
    evidence.extend("event:" + str(e.get("title", ""))[:60] for e in events.get(theme, [])[:2])
    return evidence[:5]


def _build_candidates(
    themes: list[ThemeScore],
    concept_map: dict[str, list[str]],
    sector_map: dict[str, str],
    features: dict[str, dict[str, Any]],
    name_map: dict[str, str],
    cfg: ThemeRadarConfig,
) -> list[StrategicCandidate]:
    candidates: list[StrategicCandidate] = []
    for theme in themes:
        if theme.score < cfg.min_theme_score:
            continue
        rows = _candidate_rows(theme, concept_map, sector_map, features, name_map)
        for row in rows[: cfg.max_candidates_per_theme]:
            score = _clamp(0.50 * row["leader_score"] + 0.30 * row["structure_score"] + 0.20 * theme.score)
            if score >= cfg.min_stock_score:
                candidates.append(_candidate_from_row(row, theme, score))
    return sorted(candidates, key=lambda item: item.stock_score, reverse=True)


def _candidate_rows(
    theme: ThemeScore,
    concept_map: dict[str, list[str]],
    sector_map: dict[str, str],
    features: dict[str, dict[str, Any]],
    name_map: dict[str, str],
) -> list[dict[str, Any]]:
    rows = []
    for code in _theme_members(theme.theme, concept_map, sector_map):
        if code in features:
            rows.append({"code": code, "name": name_map.get(code, code), **features[code]})
    rows = sorted(rows, key=lambda row: (row["leader_score"], row["structure_score"]), reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["theme_rank"] = idx
    return rows


def _candidate_from_row(row: dict[str, Any], theme: ThemeScore, score: float) -> StrategicCandidate:
    reasons = [
        f"RPS60/120/250={row.get('rps60', 0.0):.2f}/{row.get('rps120', 0.0):.2f}/{row.get('rps250', 0.0):.2f}",
        f"Ret60/120/250={float(row.get('ret60') or 0.0):.0f}%/{float(row.get('ret120') or 0.0):.0f}%/{float(row.get('ret250') or 0.0):.0f}%",
        f"主题内排名={int(row.get('theme_rank') or 0)}",
        f"近120日新高={int(bool(row.get('near_high_120d')))} / 距新高{int(row.get('breakout_age_days') or 0)}日",
        f"DD120={float(row.get('drawdown120') or 0.0):.1f}%",
    ]
    return StrategicCandidate(
        code=str(row["code"]),
        name=str(row.get("name") or row["code"]),
        theme=theme.theme,
        theme_score=theme.score,
        stock_score=round(score, 4),
        leader_score=round(float(row.get("leader_score") or 0.0), 4),
        theme_rank=int(row.get("theme_rank") or 0),
        ret60=round(float(row.get("ret60") or 0.0), 4),
        ret120=round(float(row.get("ret120") or 0.0), 4),
        ret250=round(float(row.get("ret250") or 0.0), 4),
        near_high_120d=bool(row.get("near_high_120d")),
        breakout_age_days=int(row.get("breakout_age_days") or 0),
        state=theme.state,
        reasons=reasons,
    )


def _ret_pct(close: pd.Series, lookback: int) -> float:
    if len(close) <= lookback:
        return 0.0
    start = float(close.iloc[-lookback - 1])
    end = float(close.iloc[-1])
    return 0.0 if start <= 0 else (end - start) / start * 100.0


def _above_ma(close: pd.Series, window: int) -> float:
    if close.empty:
        return 0.0
    ma = close.rolling(window, min_periods=max(3, min(window, len(close)))).mean().iloc[-1]
    return 1.0 if pd.notna(ma) and float(close.iloc[-1]) >= float(ma) else 0.0


def _drawdown_pct(close: pd.Series, lookback: int) -> float:
    recent = close.tail(max(lookback, 1))
    if recent.empty:
        return 0.0
    high = float(recent.max())
    return 0.0 if high <= 0 else (float(recent.iloc[-1]) / high - 1.0) * -100.0


def _near_high(close: pd.Series, lookback: int, tolerance_pct: float = 12.0) -> float:
    if close.empty:
        return 0.0
    return 1.0 if _drawdown_pct(close, lookback) <= tolerance_pct else 0.0


def _days_since_high(close: pd.Series, lookback: int) -> int:
    recent = close.tail(max(lookback, 1)).reset_index(drop=True)
    if recent.empty:
        return 999
    return int(len(recent) - 1 - int(recent.idxmax()))


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(result):
        return None
    return result


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
