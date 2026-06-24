"""Data preparation workflow for the A-share funnel job."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from core.market_breadth import calc_market_breadth
from core.wyckoff_engine import FunnelConfig
from integrations.fetch_a_share_csv import resolve_trading_window
from integrations.funnel_snapshot import dump_full_fetch_snapshot
from integrations.index_data_source import fetch_index_hist
from integrations.market_metadata import (
    detect_theme_lines,
    fetch_concept_heat,
    fetch_concept_map,
    fetch_market_cap_map,
    fetch_sector_map,
    update_concept_heat_history,
)
from tools.data_fetcher import fetch_all_ohlcv
from tools.external_seeds import (
    ExternalSeedConfig,
    append_external_symbols,
    load_external_seed_config,
)
from tools.market_liquidity import calc_amount_distribution_health, calc_market_money_flow
from tools.market_regime import analyze_benchmark_and_tune_cfg
from tools.symbol_pool import load_stock_name_map, resolve_symbol_pool, resolve_symbol_pool_from_env
from utils.env import parse_int_env
from utils.trading_clock import resolve_end_calendar_day
from workflows.fetch_runtime_config import fetch_runtime_config_from_env
from workflows.funnel_config_overrides import apply_funnel_cfg_overrides
from workflows.funnel_etf import run_etf_enhancement
from workflows.funnel_settings import (
    BATCH_SIZE,
    BATCH_SLEEP,
    BATCH_TIMEOUT,
    BREADTH_MA_WINDOW,
    EXECUTOR_MODE,
    FUNNEL_EXPORT_DIR,
    FUNNEL_EXPORT_FULL_FETCH,
    MAX_WORKERS,
    SMALLCAP_BENCH_CODE,
    TRADING_DAYS,
)
from workflows.market_liquidity_config import amount_distribution_config_from_env, market_money_flow_config_from_env
from workflows.market_regime_config import market_regime_config_from_env

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FunnelSymbolPool:
    symbols: list[str]
    pool_name_map: dict[str, str]
    stats: dict
    external_seed_cfg: ExternalSeedConfig
    external_added_to_pool: int
    main_count: int
    chinext_count: int
    star_count: int
    merged_count: int
    st_excluded_count: int
    total_batches: int


@dataclass(frozen=True)
class FunnelReferenceData:
    sector_map: dict[str, str]
    concept_map: dict[str, list[str]]
    concept_heat: list[dict]
    hot_concepts: list
    market_cap_map: dict[str, float]
    financial_map: dict[str, dict]
    name_map: dict[str, str]


@dataclass(frozen=True)
class FunnelJobData:
    cfg: FunnelConfig
    window: Any
    pool: FunnelSymbolPool
    ref_data: FunnelReferenceData
    bench_df: pd.DataFrame | None
    smallcap_df: pd.DataFrame | None
    all_df_map: dict[str, pd.DataFrame]
    fetch_stats: dict
    snapshot_dir: str
    etf_symbols: list[str]
    etf_sector_map: dict[str, str]
    etf_df_map: dict[str, pd.DataFrame]
    etf_l2_passed: list[str]
    etf_candidates: list[dict]
    benchmark_context: dict


def prepare_funnel_job_data(
    direct_source: bool,
    *,
    enforce_target_trade_date: bool = False,
    pool_board: str | None = None,
    executor_mode: str | None = None,
) -> FunnelJobData:
    cfg = FunnelConfig(trading_days=TRADING_DAYS)
    apply_funnel_cfg_overrides(cfg)
    window = resolve_trading_window(
        end_calendar_day=_resolve_funnel_end_calendar_day(),
        trading_days=TRADING_DAYS,
    )
    start_s = window.start_trade_date.strftime("%Y%m%d")
    end_s = window.end_trade_date.strftime("%Y%m%d")
    pool = _resolve_funnel_symbol_pool(pool_board)
    ref_data = _load_reference_data(pool.symbols, window, cfg)
    bench_df, smallcap_df = _load_benchmark_indices(start_s, end_s)
    all_df_map, fetch_stats = fetch_all_ohlcv(
        symbols=pool.symbols,
        window=window,
        enforce_target_trade_date=enforce_target_trade_date,
        batch_size=BATCH_SIZE,
        max_workers=MAX_WORKERS,
        batch_timeout=BATCH_TIMEOUT,
        batch_sleep=BATCH_SLEEP,
        executor_mode=_resolve_executor_mode(executor_mode),
        direct_source=direct_source,
        runtime_config=fetch_runtime_config_from_env(),
    )
    snapshot_dir = dump_full_fetch_snapshot(
        enabled=FUNNEL_EXPORT_FULL_FETCH,
        export_dir=FUNNEL_EXPORT_DIR,
        df_map=all_df_map,
        all_symbols=pool.symbols,
        window=window,
        fetch_stats=fetch_stats,
        bench_df=bench_df,
        smallcap_df=smallcap_df,
    )
    etf = run_etf_enhancement(cfg, window, bench_df, ref_data.sector_map, all_df_map, direct_source=direct_source)
    benchmark_context = _build_benchmark_context(all_df_map, bench_df, smallcap_df, cfg)
    return FunnelJobData(
        cfg=cfg,
        window=window,
        pool=pool,
        ref_data=ref_data,
        bench_df=bench_df,
        smallcap_df=smallcap_df,
        all_df_map=all_df_map,
        fetch_stats=fetch_stats,
        snapshot_dir=snapshot_dir,
        etf_symbols=etf[0],
        etf_sector_map=etf[1],
        etf_df_map=etf[2],
        etf_l2_passed=etf[3],
        etf_candidates=etf[4],
        benchmark_context=benchmark_context,
    )


def _resolve_funnel_end_calendar_day() -> date:
    raw = os.getenv("END_CALENDAR_DAY", "").strip()
    if raw:
        try:
            return pd.to_datetime(raw).date()
        except Exception as e:
            logger.warning("END_CALENDAR_DAY=%r 解析失败，回退自动日期: %s", raw, e)
    return resolve_end_calendar_day()


def _load_benchmark_indices(start_s: str, end_s: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    bench_df = smallcap_df = None
    try:
        bench_df = fetch_index_hist("000001", start_s, end_s)
        print("[funnel] 大盘基准加载成功")
    except Exception as e:
        logger.error("大盘基准加载失败: %s", e, exc_info=True)
    try:
        smallcap_df = fetch_index_hist(SMALLCAP_BENCH_CODE, start_s, end_s)
        print(f"[funnel] 小盘基准加载成功: {SMALLCAP_BENCH_CODE}")
    except Exception as e:
        logger.error("小盘基准加载失败 %s: %s", SMALLCAP_BENCH_CODE, e, exc_info=True)
    return bench_df, smallcap_df


def _resolve_external_seed_pool(all_symbols: list[str]) -> tuple[ExternalSeedConfig, list[str], int]:
    seed_cfg = load_external_seed_config()
    merged, added = append_external_symbols(all_symbols, seed_cfg)
    if seed_cfg.enabled:
        print(
            "[funnel] 外部观察名单: "
            f"source={seed_cfg.source}, seeds={len(seed_cfg.symbols)}, "
            f"added_to_pool={added}, mode=shadow_only"
        )
    return seed_cfg, merged, added


def _resolve_funnel_symbol_pool(pool_board: str | None = None) -> FunnelSymbolPool:
    if pool_board:
        all_symbols, pool_name_map, pool_stats = resolve_symbol_pool(
            pool_mode="board",
            board_name=pool_board,
            limit_count=parse_int_env("FUNNEL_POOL_LIMIT_COUNT", 0),
        )
    else:
        all_symbols, pool_name_map, pool_stats = resolve_symbol_pool_from_env()
    seed_cfg, all_symbols, external_added = _resolve_external_seed_pool(all_symbols)
    main_count = int(pool_stats.get("pool_main", 0) or 0)
    chinext_count = int(pool_stats.get("pool_chinext", 0) or 0)
    star_count = int(pool_stats.get("pool_star", 0) or 0)
    st_excluded_count = int(pool_stats.get("pool_st_excluded", 0) or 0)
    total_batches = (len(all_symbols) + BATCH_SIZE - 1) // BATCH_SIZE if all_symbols else 0
    print(
        "[funnel] 股票池统计: "
        f"mode={pool_stats.get('pool_mode')}, main={main_count}, chinext={chinext_count}, "
        f"star={star_count}, merged={len(pool_name_map)}, st_excluded={st_excluded_count}, "
        f"final={len(all_symbols)}, limit={pool_stats.get('pool_limit', 0)}, "
        f"batches={total_batches} (batch_size={BATCH_SIZE})"
    )
    _report_progress("股票池加载", f"共{len(all_symbols)}只", 0.05)
    return FunnelSymbolPool(
        symbols=all_symbols,
        pool_name_map=pool_name_map,
        stats=pool_stats,
        external_seed_cfg=seed_cfg,
        external_added_to_pool=external_added,
        main_count=main_count,
        chinext_count=chinext_count,
        star_count=star_count,
        merged_count=len(pool_name_map),
        st_excluded_count=st_excluded_count,
        total_batches=total_batches,
    )


def _resolve_executor_mode(raw: str | None) -> str:
    mode = str(raw or EXECUTOR_MODE or "process").strip().lower()
    return mode if mode in {"thread", "process"} else "process"


def _load_market_metadata(window, cfg: FunnelConfig) -> tuple[dict, dict, list[dict], list, dict[str, float]]:
    print("[funnel] 加载行业映射...")
    try:
        sector_map = fetch_sector_map()
    except Exception as e:
        logger.warning("行业映射加载失败，降级为空映射: %s", e)
        sector_map = {}
    print("[funnel] 加载概念映射...")
    try:
        concept_map = fetch_concept_map()
    except Exception as e:
        logger.warning("概念映射加载失败，降级为空映射: %s", e)
        concept_map = {}
    print("[funnel] 加载概念热度...")
    try:
        concept_heat = fetch_concept_heat()
    except Exception as e:
        logger.warning("概念热度加载失败: %s", e)
        concept_heat = []
    if concept_heat:
        update_concept_heat_history(window.end_trade_date.isoformat(), concept_heat, top_n=cfg.theme_line_top_n)
    hot_concepts = detect_theme_lines(min_days=cfg.theme_line_min_days)
    print("[funnel] 加载市值数据...")
    try:
        market_cap_map = fetch_market_cap_map()
    except Exception as e:
        logger.warning("市值数据加载失败，降级为空映射: %s", e)
        market_cap_map = {}
    if not market_cap_map:
        print("[funnel] ⚠️ 市值数据为空（TUSHARE_TOKEN 可能缺失/失效），Layer1 将跳过市值过滤")
    return sector_map, concept_map, concept_heat, hot_concepts, market_cap_map


def _load_financial_metrics(all_symbols: list[str]) -> dict[str, dict]:
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        return {}
    try:
        from integrations.tickflow_client import TickFlowClient

        client = TickFlowClient(api_key=api_key)
        print(f"[funnel] TickFlow 财务指标请求: symbols={len(all_symbols)}")
        raw_fin = client.get_financial_metrics(all_symbols, latest=True)
        financial_map = {sym: records[0] for sym, records in raw_fin.items() if records}
        missing = max(len(all_symbols) - len(financial_map), 0)
        sample_missing = ",".join(sorted([s for s in all_symbols if s not in financial_map])[:8])
        print(
            f"[funnel] TickFlow 财务指标加载成功: {len(financial_map)}/{len(all_symbols)}, "
            f"missing={missing}, sample_missing={sample_missing or '-'}"
        )
        return financial_map
    except Exception as e:
        logger.warning("TickFlow 财务指标加载失败，跳过财务过滤: %s", e)
        return {}


def _load_stock_names() -> dict[str, str]:
    print("[funnel] 加载股票名称...")
    try:
        return load_stock_name_map()
    except Exception as e:
        logger.warning("股票名称加载失败，降级为代码展示: %s", e)
        return {}


def _load_reference_data(all_symbols: list[str], window, cfg: FunnelConfig) -> FunnelReferenceData:
    sector_map, concept_map, concept_heat, hot_concepts, market_cap_map = _load_market_metadata(window, cfg)
    return FunnelReferenceData(
        sector_map=sector_map,
        concept_map=concept_map,
        concept_heat=concept_heat,
        hot_concepts=hot_concepts,
        market_cap_map=market_cap_map,
        financial_map=_load_financial_metrics(all_symbols),
        name_map=_load_stock_names(),
    )


def _build_benchmark_context(
    all_df_map: dict[str, pd.DataFrame],
    bench_df: pd.DataFrame | None,
    smallcap_df: pd.DataFrame | None,
    cfg: FunnelConfig,
) -> dict:
    breadth_context = calc_market_breadth(all_df_map, BREADTH_MA_WINDOW)
    money_flow_context = calc_market_money_flow(
        all_df_map,
        breadth_context,
        config=market_money_flow_config_from_env(),
    )
    amount_distribution_context = calc_amount_distribution_health(
        all_df_map,
        cfg.min_avg_amount_wan,
        cfg.amount_avg_window,
        config=amount_distribution_config_from_env(),
    )
    benchmark_context = analyze_benchmark_and_tune_cfg(
        bench_df,
        smallcap_df,
        cfg,
        breadth=breadth_context,
        money_flow=money_flow_context,
        amount_distribution=amount_distribution_context,
        regime_config=market_regime_config_from_env(),
    )
    _print_benchmark_gate(benchmark_context)
    return benchmark_context


def _print_benchmark_gate(benchmark_context: dict) -> None:
    print(
        "[funnel] 大盘总闸: "
        f"regime={benchmark_context['regime']}, "
        f"close={benchmark_context['close']}, ma50={benchmark_context['ma50']}, ma200={benchmark_context['ma200']}, "
        f"ma50_slope_5d={benchmark_context['ma50_slope_5d']}, main_today={benchmark_context.get('main_today_pct')}, "
        f"recent3={benchmark_context['recent3_pct']}, recent3_cum={benchmark_context['recent3_cum_pct']}, "
        f"smallcap_code={benchmark_context.get('smallcap_code')}, "
        f"smallcap_today={benchmark_context.get('smallcap_today_pct')}, "
        f"breadth={benchmark_context.get('breadth')}, money_flow={benchmark_context.get('money_flow')}, "
        f"amount_distribution={benchmark_context.get('amount_distribution')}, "
        f"holiday_grace={benchmark_context.get('holiday_grace_dynamic')}, "
        f"pv_policy_shadow={benchmark_context.get('market_pv_policy_shadow')}, "
        f"panic_triggered={benchmark_context.get('panic_triggered')}, "
        f"panic_reasons={benchmark_context.get('panic_reasons')}, "
        f"repair_triggered={benchmark_context.get('repair_triggered')}, "
        f"repair_reasons={benchmark_context.get('repair_reasons')}, tuned={benchmark_context['tuned']}"
    )


def _report_progress(stage: str, message: str, progress: float) -> None:
    from utils.progress import report_progress

    report_progress(stage, message, progress)
