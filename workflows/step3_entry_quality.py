"""Entry-quality annotations for Step3 candidate context."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def annotate_entry_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Attach deterministic entry-quality fields to Step3 candidates."""

    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    out = df.copy()
    scores = [_entry_quality_row(row) for _, row in out.iterrows()]
    out["entry_quality_score"] = [item["score"] for item in scores]
    out["entry_quality_grade"] = [item["grade"] for item in scores]
    out["entry_quality_tag"] = [item["tag"] for item in scores]
    out["entry_risk_flags"] = [item["risk_flags"] for item in scores]
    out["entry_priority_bucket"] = _priority_bucket(out)
    return out


def entry_quality_policy_tag(row: pd.Series) -> str:
    tag = _clean(row.get("entry_quality_tag"))
    risks = _clean(row.get("entry_risk_flags"))
    if tag and risks:
        return f"{tag}；风险: {risks}"
    return tag or (f"风险: {risks}" if risks else "")


def _entry_quality_row(row: pd.Series) -> dict[str, Any]:
    rs10 = _num(row.get("rs_10"))
    dry = _num(row.get("min_vol_ratio_5d"))
    bias = _num(row.get("bias_200"))
    amount = _num(row.get("avg_amount_20_yi"))
    score = 35.0 + _rs_points(rs10) + _dry_points(dry) + _bias_points(bias) + _liquidity_points(amount)
    risks = _risk_flags(rs10, dry, bias, amount)
    score = round(max(0.0, min(100.0, score)), 1)
    grade = _grade(score)
    return {
        "score": score,
        "grade": grade,
        "tag": f"入场质量{grade}({score:.1f})",
        "risk_flags": "、".join(risks),
    }


def _priority_bucket(df: pd.DataFrame) -> pd.Series:
    raw = _finite_series(df.get("priority_score"), df.index)
    raw = raw.where(raw.notna(), _finite_series(df.get("funnel_score"), df.index))
    return (raw.fillna(0.0) / 5.0).apply(math.floor)


def _rs_points(value: float | None) -> float:
    if value is None:
        return 0.0
    if value >= 8:
        return 18.0
    if value >= 3:
        return 12.0
    if value >= 0:
        return 6.0
    return -8.0


def _dry_points(value: float | None) -> float:
    if value is None:
        return 0.0
    if 0.35 <= value <= 0.85:
        return 18.0
    if 0.85 < value <= 1.25:
        return 8.0
    if value < 0.35:
        return -4.0
    return -10.0


def _bias_points(value: float | None) -> float:
    if value is None:
        return 0.0
    if -5 <= value <= 18:
        return 18.0
    if 18 < value <= 32:
        return 8.0
    if value < -12:
        return -8.0
    if value > 45:
        return -16.0
    return 0.0


def _liquidity_points(value: float | None) -> float:
    if value is None:
        return 0.0
    if value >= 3:
        return 8.0
    if value >= 1:
        return 4.0
    return -6.0


def _risk_flags(
    rs10: float | None,
    dry: float | None,
    bias: float | None,
    amount: float | None,
) -> list[str]:
    risks: list[str] = []
    if rs10 is not None and rs10 < 0:
        risks.append("弱于指数")
    if dry is not None and dry > 1.35:
        risks.append("缩量不足")
    if dry is not None and dry < 0.3:
        risks.append("流动性萎缩")
    if bias is not None and bias > 45:
        risks.append("追高延展")
    if bias is not None and bias < -12:
        risks.append("长线弱势")
    if amount is not None and amount < 1:
        risks.append("成交额偏低")
    return risks


def _grade(score: float) -> str:
    if score >= 80:
        return "S"
    if score >= 70:
        return "A"
    if score >= 58:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _finite_series(raw: Any, index: pd.Index) -> pd.Series:
    if raw is None:
        return pd.Series(pd.NA, index=index, dtype="Float64")
    converted = pd.to_numeric(raw, errors="coerce")
    series = converted if isinstance(converted, pd.Series) else pd.Series(converted, index=index)
    series = series.reindex(index)
    return series.where(series.map(lambda value: _num(value) is not None))


def _num(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _clean(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value or "").strip()
