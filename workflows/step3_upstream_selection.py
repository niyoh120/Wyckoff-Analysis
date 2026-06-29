"""Step3 selection path that preserves upstream candidate priority."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from core.ai_candidate_allocation import fit_ai_candidate_quotas
from workflows.step3_runtime_config import Step3RuntimeConfig
from workflows.step3_text import coerce_bool_like


def has_upstream_priority_context(candidates_df: pd.DataFrame, runtime_config: Step3RuntimeConfig) -> bool:
    if not runtime_config.respect_upstream_priority or candidates_df is None or candidates_df.empty:
        return False
    if (
        "priority_score" in candidates_df.columns
        and finite_numeric_series(candidates_df["priority_score"], candidates_df.index).notna().any()
    ):
        return True
    return (
        "selection_source" in candidates_df.columns
        and candidates_df["selection_source"].astype(str).str.strip().ne("").any()
    )


def select_upstream_priority_candidates(
    candidates_df: pd.DataFrame,
    runtime_config: Step3RuntimeConfig,
    context_cap: int,
) -> pd.DataFrame:
    df = _prepare_upstream_frame(candidates_df)
    if context_cap <= 0 or len(df) <= context_cap:
        selected_df = df
    else:
        selected_df = _select_capped_upstream_candidates(df, runtime_config, context_cap)
    _log_upstream_selection(candidates_df, selected_df, context_cap)
    return selected_df.reset_index(drop=True)


def _select_capped_upstream_candidates(
    df: pd.DataFrame,
    runtime_config: Step3RuntimeConfig,
    context_cap: int,
) -> pd.DataFrame:
    trend_total = int((df["track"] == "Trend").sum())
    accum_total = int((df["track"] == "Accum").sum())
    trend_cap, accum_cap = fit_ai_candidate_quotas(context_cap, trend_total, accum_total)
    core_df = _priority_ordered(df[~df["selection_is_fill"]])
    fill_df = _priority_ordered(df[df["selection_is_fill"]])
    selected_df = _take_track_core_candidates(core_df, trend_cap, accum_cap)
    selected_df = _append_remaining_core(selected_df, core_df, context_cap)
    return _append_fill_candidates(selected_df, fill_df, context_cap, runtime_config.max_upstream_fill)


def _prepare_upstream_frame(candidates_df: pd.DataFrame) -> pd.DataFrame:
    if candidates_df is None or candidates_df.empty:
        return pd.DataFrame()
    df = candidates_df.copy()
    df["input_order"] = pd.to_numeric(df.get("input_order"), errors="coerce")
    df["input_order"] = df["input_order"].fillna(pd.Series(range(len(df)), index=df.index)).astype(int)
    if "selection_is_fill" in df.columns:
        df["selection_is_fill"] = df["selection_is_fill"].apply(coerce_bool_like)
    else:
        df["selection_is_fill"] = False
    df["priority_score"] = finite_numeric_series(df.get("priority_score"), df.index)
    return df.sort_values(by=["selection_is_fill", "input_order"], ascending=[True, True], kind="stable").reset_index(
        drop=True
    )


def finite_numeric_series(raw: Any, index: pd.Index) -> pd.Series:
    if raw is None:
        return pd.Series(pd.NA, index=index, dtype="Float64")
    converted = pd.to_numeric(raw, errors="coerce")
    series = converted if isinstance(converted, pd.Series) else pd.Series(converted, index=index)
    series = series.reindex(index)
    finite_mask = series.map(lambda value: math.isfinite(float(value)) if pd.notna(value) else False)
    return series.where(finite_mask)


def _priority_ordered(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "priority_score" not in df.columns or not df["priority_score"].notna().any():
        return df.sort_values("input_order", kind="stable")
    return df.sort_values(by=["priority_score", "input_order"], ascending=[False, True], kind="stable")


def _take_track_core_candidates(core_df: pd.DataFrame, trend_cap: int, accum_cap: int) -> pd.DataFrame:
    selected_parts: list[pd.DataFrame] = []
    if trend_cap > 0:
        selected_parts.append(core_df[core_df["track"] == "Trend"].head(trend_cap))
    if accum_cap > 0:
        selected_parts.append(core_df[core_df["track"] == "Accum"].head(accum_cap))
    return pd.concat(selected_parts, ignore_index=False) if selected_parts else core_df.iloc[0:0].copy()


def _append_remaining_core(selected_df: pd.DataFrame, core_df: pd.DataFrame, context_cap: int) -> pd.DataFrame:
    remaining_slots = max(context_cap - len(selected_df), 0)
    if remaining_slots <= 0:
        return selected_df
    selected_codes = set(selected_df["code"].astype(str).tolist())
    core_remainder = core_df[~core_df["code"].astype(str).isin(selected_codes)]
    if core_remainder.empty:
        return selected_df
    return pd.concat([selected_df, core_remainder.head(remaining_slots)], ignore_index=False)


def _append_fill_candidates(
    selected_df: pd.DataFrame,
    fill_df: pd.DataFrame,
    context_cap: int,
    max_upstream_fill: int,
) -> pd.DataFrame:
    remaining_slots = max(context_cap - len(selected_df), 0)
    if remaining_slots <= 0 or max_upstream_fill <= 0:
        return selected_df
    selected_codes = set(selected_df["code"].astype(str).tolist())
    fill_remainder = fill_df[~fill_df["code"].astype(str).isin(selected_codes)]
    if fill_remainder.empty:
        return selected_df
    fill_take = fill_remainder.head(min(remaining_slots, max_upstream_fill))
    return pd.concat([selected_df, fill_take], ignore_index=False)


def _log_upstream_selection(candidates_df: pd.DataFrame, selected_df: pd.DataFrame, context_cap: int) -> None:
    fill_count = int(selected_df.get("selection_is_fill", pd.Series(dtype=bool)).sum())
    track_counts = selected_df["track"].value_counts().to_dict() if "track" in selected_df.columns else {}
    print(
        f"[step3] 尊重上游优先级收口: raw={len(candidates_df)} -> selected={len(selected_df)} "
        f"(cap={context_cap}, Trend={int(track_counts.get('Trend', 0))}, "
        f"Accum={int(track_counts.get('Accum', 0))}, fills={fill_count})"
    )
