"""Step3 candidate compression for model context budgeting."""

from __future__ import annotations

import pandas as pd

from workflows.step3_runtime_config import Step3RuntimeConfig

DYNAMIC_MAINLINE_BONUS_RATE = 0.15
DYNAMIC_MAINLINE_TOP_N = 3
DYNAMIC_MAINLINE_MIN_CLUSTER = 2


def select_compressed_step3_candidates(
    candidates_df: pd.DataFrame,
    regime: str,
    runtime_config: Step3RuntimeConfig,
    effective_context_cap: int,
) -> pd.DataFrame:
    selected_df = _compress_step3_candidates(
        candidates_df,
        regime=regime,
        bonus_rate=DYNAMIC_MAINLINE_BONUS_RATE,
        max_total=effective_context_cap,
        max_per_industry=runtime_config.max_per_industry,
    )
    if selected_df.empty:
        selected_df = _fallback_candidates_when_compression_empty(
            candidates_df,
            runtime_config.empty_compression_fallback_cap,
        )
        print(
            "[step3] 压缩器结果为空，回退为受控候选列表 "
            f"(fallback_cap={runtime_config.empty_compression_fallback_cap}, selected={len(selected_df)})"
        )
    print(
        f"[step3] 候选压缩已启用: raw={len(candidates_df)} -> selected={len(selected_df)} "
        f"(regime={regime}, max_total={effective_context_cap}, max_per_industry={runtime_config.max_per_industry})"
    )
    return selected_df


def _compress_step3_candidates(
    candidates_df: pd.DataFrame,
    *,
    regime: str | None,
    bonus_rate: float,
    max_total: int,
    max_per_industry: int,
) -> pd.DataFrame:
    df = _prepare_compression_frame(candidates_df)
    if df.empty:
        return pd.DataFrame()
    df = _apply_bias_filter(df, regime)
    if df.empty:
        return pd.DataFrame()
    df = _score_compression_factors(df)
    hot_industries = _hot_mainline_industries(df)
    df = _apply_mainline_bonus(df, hot_industries, bonus_rate)
    df = _limit_by_industry(df, max_total, max_per_industry)
    _log_hot_industries(hot_industries)
    return df


def _prepare_compression_frame(candidates_df: pd.DataFrame) -> pd.DataFrame:
    if candidates_df is None or candidates_df.empty:
        return pd.DataFrame()
    df = candidates_df.copy()
    df["code"] = df.get("code", "").astype(str).str.strip()
    df["bias_200"] = pd.to_numeric(df.get("bias_200"), errors="coerce")
    df["rs_10"] = pd.to_numeric(df.get("rs_10"), errors="coerce")
    df["min_vol_ratio_5d"] = pd.to_numeric(df.get("min_vol_ratio_5d"), errors="coerce")
    df["industry"] = df.get("industry", "").astype(str).str.strip()
    df.loc[df["industry"] == "", "industry"] = pd.NA
    return df.dropna(subset=["bias_200", "rs_10", "min_vol_ratio_5d", "industry"])


def _apply_bias_filter(df: pd.DataFrame, regime: str | None) -> pd.DataFrame:
    bias_min, bias_max = _resolve_bias_range(regime)
    return df[(df["bias_200"] >= bias_min) & (df["bias_200"] <= bias_max)]


def _resolve_bias_range(regime: str | None) -> tuple[float, float]:
    r = str(regime or "").upper()
    if r == "BLACK_SWAN":
        return (0.0, 15.0)
    if r == "CRASH":
        return (0.0, 20.0)
    if r == "RISK_ON":
        return (-5.0, 45.0)
    if r == "RISK_OFF":
        return (0.0, 25.0)
    return (0.0, 35.0)


def _score_compression_factors(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rs_score"] = df["rs_10"].rank(pct=True, ascending=True, method="average")
    df["dry_score"] = df["min_vol_ratio_5d"].rank(pct=True, ascending=False, method="average")
    df["base_wyckoff_score"] = 0.6 * df["rs_score"] + 0.4 * df["dry_score"]
    return df


def _hot_mainline_industries(df: pd.DataFrame) -> set[str]:
    industry_stats = df.groupby("industry", as_index=False).agg(
        stock_count=("code", "count"),
        avg_rs=("rs_score", "mean"),
    )
    valid_stats = industry_stats[industry_stats["stock_count"] >= DYNAMIC_MAINLINE_MIN_CLUSTER]
    if valid_stats.empty:
        return set()
    return set(valid_stats.nlargest(DYNAMIC_MAINLINE_TOP_N, "avg_rs")["industry"].astype(str).tolist())


def _format_mainline_tag(industry: str | None, is_hot: bool) -> str:
    if not is_hot or not industry:
        return ""
    return f"🔥 [当前资金最强主线: {industry}]"


def _apply_mainline_bonus(df: pd.DataFrame, hot_industries: set[str], bonus_rate: float) -> pd.DataFrame:
    df = df.copy()
    df["is_hot_mainline"] = df["industry"].astype(str).isin(hot_industries)
    df["policy_tag"] = df.apply(
        lambda r: _format_mainline_tag(str(r.get("industry", "")), bool(r.get("is_hot_mainline"))),
        axis=1,
    )
    df["dynamic_bonus"] = df["is_hot_mainline"].map(lambda v: float(bonus_rate) if bool(v) else 0.0)
    df["wyckoff_score"] = df["base_wyckoff_score"] * (1.0 + df["dynamic_bonus"])
    return df


def _limit_by_industry(df: pd.DataFrame, max_total: int, max_per_industry: int) -> pd.DataFrame:
    total_cap = max_total if max_total > 0 else len(df)
    industry_cap = max_per_industry if max_per_industry > 0 else len(df)
    df = df.sort_values("wyckoff_score", ascending=False).copy()
    df["industry_rank"] = df.groupby("industry")["wyckoff_score"].rank(ascending=False, method="first").astype(int)
    return df.groupby("industry", group_keys=False).head(industry_cap).head(total_cap).reset_index(drop=True)


def _fallback_candidates_when_compression_empty(candidates_df: pd.DataFrame, fallback_cap: int) -> pd.DataFrame:
    if candidates_df is None or candidates_df.empty:
        return pd.DataFrame()
    df = candidates_df.copy()
    df["wyckoff_score"] = pd.to_numeric(df.get("funnel_score"), errors="coerce")
    df = df.sort_values(
        by=["wyckoff_score", "rs_10", "min_vol_ratio_5d"],
        ascending=[False, False, True],
        na_position="last",
    ).reset_index(drop=True)
    return df.head(fallback_cap).reset_index(drop=True) if fallback_cap > 0 else df


def _log_hot_industries(hot_industries: set[str]) -> None:
    if hot_industries:
        print(f"[step3] 动态主线行业: {', '.join(sorted(hot_industries))}")
    else:
        print("[step3] 动态主线行业: 无（未形成有效行业集群）")
