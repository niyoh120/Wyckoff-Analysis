from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

if __name__ == "__main__" or not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.signal_confirmation import score_springboard_abc
from core.wyckoff_engine import (
    FunnelConfig,
    layer1_filter,
    layer2_strength_detailed,
    layer3_sector_resonance,
    layer4_triggers,
    normalize_hist_from_fetch,
)
from integrations.data_source import fetch_index_hist, fetch_market_cap_map, fetch_sector_map, fetch_stock_hist
from integrations.fetch_a_share_csv import get_stocks_by_board
from integrations.tickflow_client import TickFlowClient
from scripts.market_funnel_job import funnel_config_for_market
from tools.candidate_ranker import TRIGGER_LABELS, TRIGGER_SHORT_LABELS
from tools.market_universe_meta import load_symbol_name_map
from utils.feishu import send_feishu_notification

MIN_RPS_UNIVERSE_HISTORIES = 500


@dataclass(frozen=True)
class SymbolSpec:
    market: str
    symbol: str
    label: str


@dataclass(frozen=True)
class ReplayContext:
    name_map: dict[str, str]
    market_cap_map: dict[str, float]
    sector_map: dict[str, str]
    bench_df: pd.DataFrame | None


@dataclass
class DayDiagnostic:
    date: str
    status: str
    failed_layer: str
    reason: str
    triggers: str
    trigger_scores: str
    abc_grade: str
    abc_count: int
    channel: str
    close: float | None
    pct_chg: float | None
    vol_ratio: float | None
    amount_avg_wan: float | None
    ma50: float | None
    ma200: float | None


def detect_symbol_market(raw_symbol: str) -> SymbolSpec:
    raw = str(raw_symbol or "").strip().upper()
    if not raw:
        raise ValueError("symbol 不能为空")
    if re.fullmatch(r"\d{6}(\.(SH|SZ|BJ))?", raw):
        return SymbolSpec("cn", raw.split(".", 1)[0], "A股")
    if raw.endswith(".HK") or re.fullmatch(r"\d{1,5}", raw):
        base = raw.replace(".HK", "")
        return SymbolSpec("hk", f"{base.zfill(5)}.HK", "港股")
    if raw.endswith(".US"):
        return SymbolSpec("us", raw, "美股")
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", raw):
        return SymbolSpec("us", f"{raw}.US", "美股")
    raise ValueError(f"无法识别股票市场: {raw_symbol}")


def parse_ymd(value: str) -> date:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"日期格式必须是 YYYY-MM-DD: {value}") from exc


def fetch_symbol_history(spec: SymbolSpec, start: date, end: date, trading_days: int) -> pd.DataFrame:
    fetch_start = start - timedelta(days=max(trading_days * 3, 760))
    if spec.market == "cn":
        raw = fetch_stock_hist(spec.symbol, fetch_start, end, adjust="qfq")
    else:
        raw = _fetch_tickflow_daily(spec.symbol, fetch_start, end, trading_days)
    return _prepare_history(raw, start, end, trading_days)


def _fetch_tickflow_daily(symbol: str, start: date, end: date, trading_days: int) -> pd.DataFrame:
    client = TickFlowClient(api_key=os.getenv("TICKFLOW_API_KEY", ""))
    start_ms = _date_to_utc_ms(start)
    end_ms = _date_to_utc_ms(end + timedelta(days=1))
    count = max((end - start).days + 10, trading_days * 3, 1200)
    return client.get_klines(
        symbol,
        period="1d",
        count=count,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        adjust="forward",
    )


def _prepare_history(raw: pd.DataFrame, start: date, end: date, trading_days: int) -> pd.DataFrame:
    df = normalize_hist_from_fetch(raw)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).copy()
    df["date_obj"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date_obj"]).sort_values("date_obj").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date_obj"]).dt.strftime("%Y-%m-%d")
    first_idx = _first_index_on_or_after(df, start)
    if first_idx is None:
        return pd.DataFrame()
    trim_from = max(first_idx - trading_days, 0)
    return df[(df.index >= trim_from) & (df["date_obj"] <= end)].reset_index(drop=True)


def _first_index_on_or_after(df: pd.DataFrame, day: date) -> int | None:
    hits = df.index[df["date_obj"] >= day]
    return int(hits[0]) if len(hits) else None


def _date_to_utc_ms(day: date) -> int:
    dt = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def build_context(spec: SymbolSpec, hist: pd.DataFrame, start: date, end: date) -> ReplayContext:
    name_map = _name_map(spec)
    if spec.market != "cn":
        return ReplayContext(name_map, {}, {}, None)
    return ReplayContext(
        name_map,
        _safe_fetch_market_cap_map(),
        _safe_fetch_sector_map(),
        _safe_fetch_benchmark(start, end, hist),
    )


def _name_map(spec: SymbolSpec) -> dict[str, str]:
    if spec.market in {"hk", "us"}:
        names = load_symbol_name_map((spec.market,))
        return {spec.symbol: names.get(spec.symbol, spec.symbol)}
    return {spec.symbol: spec.symbol}


def _safe_fetch_market_cap_map() -> dict[str, float]:
    try:
        return fetch_market_cap_map()
    except Exception as exc:
        print(f"[diagnosis] 市值映射获取失败，跳过市值精确诊断: {exc}", flush=True)
        return {}


def _safe_fetch_sector_map() -> dict[str, str]:
    try:
        return fetch_sector_map()
    except Exception as exc:
        print(f"[diagnosis] 行业映射获取失败，跳过行业精确诊断: {exc}", flush=True)
        return {}


def _safe_fetch_benchmark(start: date, end: date, hist: pd.DataFrame) -> pd.DataFrame | None:
    try:
        bench_start = min(hist["date_obj"]) if not hist.empty else start
        return fetch_index_hist("000001", bench_start, end)
    except Exception as exc:
        print(f"[diagnosis] 大盘基准获取失败，Layer2 相对强弱会降级: {exc}", flush=True)
        return None


def load_rps_universe_histories(
    spec: SymbolSpec, start: date, end: date, rps_window: int = 150
) -> dict[str, pd.DataFrame]:
    if spec.market != "cn":
        return {}
    items = get_stocks_by_board("main_chinext_star")
    symbols = [str(s["code"]).strip() for s in items if s.get("code")]
    symbols = [s for s in symbols if s and s != spec.symbol]
    if not symbols:
        return {}
    print(f"[diagnosis] RPS 全市场加载: universe={len(symbols)} symbols", flush=True)
    client = TickFlowClient(api_key=os.getenv("TICKFLOW_API_KEY", ""))
    count = rps_window + 30
    end_ms = _date_to_utc_ms(end + timedelta(days=1))
    out: dict[str, pd.DataFrame] = {}
    batch_size = 200
    chunks = [symbols[i : i + batch_size] for i in range(0, len(symbols), batch_size)]
    for idx, chunk in enumerate(chunks, 1):
        print(f"[diagnosis] RPS K线批次 {idx}/{len(chunks)}", flush=True)
        batch = client.get_klines_batch(chunk, period="1d", count=count, end_time_ms=end_ms, adjust="forward")
        for sym, df in batch.items():
            norm = normalize_hist_from_fetch(df)
            if norm is not None and len(norm) >= rps_window:
                out[sym] = norm
    print(f"[diagnosis] RPS 历史加载完成: fetched={len(out)}/{len(symbols)}", flush=True)
    return out


def config_for_symbol(spec: SymbolSpec, trading_days: int) -> FunnelConfig:
    if spec.market == "cn":
        return FunnelConfig(trading_days=trading_days)
    return funnel_config_for_market(spec.market, trading_days=trading_days)


def _build_rps_context(
    df_map: dict[str, pd.DataFrame],
    rps_histories: dict[str, pd.DataFrame] | None,
    day: date,
) -> tuple[dict[str, pd.DataFrame], list[str] | None]:
    if not rps_histories:
        return df_map, None
    merged: dict[str, pd.DataFrame] = dict(df_map)
    day_str = day.isoformat()
    for sym, full_df in rps_histories.items():
        if sym in merged:
            continue
        sliced = full_df[full_df["date"] <= day_str]
        if len(sliced) >= 50:
            merged[sym] = sliced
    return merged, list(merged.keys())


def _benchmark_for_day(bench_df: pd.DataFrame | None, day: date) -> pd.DataFrame | None:
    if bench_df is None or bench_df.empty:
        return bench_df
    return bench_df[bench_df["date"] <= day.isoformat()].copy()


def replay_symbol(
    spec: SymbolSpec,
    hist: pd.DataFrame,
    ctx: ReplayContext,
    cfg: FunnelConfig,
    start: date,
    end: date,
    rps_histories: dict[str, pd.DataFrame] | None = None,
) -> list[DayDiagnostic]:
    days = [x for x in hist["date_obj"].tolist() if start <= x <= end]
    return [_evaluate_day(spec, hist[hist["date_obj"] <= day].copy(), ctx, cfg, day, rps_histories) for day in days]


def _evaluate_day(
    spec: SymbolSpec,
    day_df: pd.DataFrame,
    ctx: ReplayContext,
    cfg: FunnelConfig,
    day: date,
    rps_histories: dict[str, pd.DataFrame] | None = None,
) -> DayDiagnostic:
    if len(day_df) < max(60, min(cfg.trading_days, 220)):
        return _diagnostic(spec, day_df, day, "MISS", "DATA", "历史数据不足，无法完成漏斗回放", {}, "")
    df_map = {spec.symbol: day_df}
    layer1 = layer1_filter([spec.symbol], ctx.name_map, ctx.market_cap_map, df_map, cfg)
    if spec.symbol not in layer1:
        return _diagnostic(spec, day_df, day, "MISS", "L1", _l1_reason(spec, day_df, ctx, cfg), {}, "")
    rps_df_map, rps_universe = _build_rps_context(df_map, rps_histories, day)
    layer2, channel_map, _ = layer2_strength_detailed(
        layer1, rps_df_map, _benchmark_for_day(ctx.bench_df, day), cfg, rps_universe=rps_universe
    )
    if spec.symbol not in layer2:
        return _diagnostic(spec, day_df, day, "MISS", "L2", _l2_reason(spec, day_df, cfg), {}, "")
    layer3, _ = layer3_sector_resonance(layer2, ctx.sector_map, cfg, base_symbols=layer1, df_map=df_map)
    if spec.symbol not in layer3:
        return _diagnostic(spec, day_df, day, "MISS", "L3", _l3_reason(spec, ctx), {}, channel_map.get(spec.symbol, ""))
    scores = _trigger_scores(layer4_triggers(layer3, df_map, cfg, channel_map), spec.symbol)
    if not scores:
        return _diagnostic(
            spec, day_df, day, "MISS", "L4", _l4_reason(day_df), scores, channel_map.get(spec.symbol, "")
        )
    return _diagnostic(
        spec, day_df, day, "SELECTED", "-", _selected_reason(scores, day_df), scores, channel_map.get(spec.symbol, "")
    )


def _trigger_scores(triggers: dict[str, list[tuple[str, float]]], symbol: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for trigger, rows in triggers.items():
        for code, score in rows:
            if code == symbol:
                out[trigger] = max(out.get(trigger, 0.0), float(score))
    return out


def _diagnostic(
    spec: SymbolSpec,
    day_df: pd.DataFrame,
    day: date,
    status: str,
    failed_layer: str,
    reason: str,
    scores: dict[str, float],
    channel: str,
) -> DayDiagnostic:
    metrics = _day_metrics(day_df)
    abc = _best_abc(day_df, list(scores))
    trigger_text = "+".join(TRIGGER_SHORT_LABELS.get(key, key) for key in scores) if scores else "-"
    score_text = ", ".join(f"{key}:{value:.2f}" for key, value in scores.items()) if scores else "-"
    return DayDiagnostic(
        date=day.isoformat(),
        status=status,
        failed_layer=failed_layer,
        reason=reason,
        triggers=trigger_text,
        trigger_scores=score_text,
        abc_grade=str(abc.get("grade", "none")),
        abc_count=int(abc.get("met_count", 0)),
        channel=channel or "-",
        close=metrics["close"],
        pct_chg=metrics["pct_chg"],
        vol_ratio=metrics["vol_ratio"],
        amount_avg_wan=metrics["amount_avg_wan"],
        ma50=metrics["ma50"],
        ma200=metrics["ma200"],
    )


def _best_abc(day_df: pd.DataFrame, trigger_keys: list[str]) -> dict[str, Any]:
    keys = trigger_keys or list(TRIGGER_LABELS)
    scored = [score_springboard_abc(day_df, key) for key in keys]
    return max(scored, key=lambda item: (int(item.get("met_count", 0)), str(item.get("grade", ""))))


def _day_metrics(df: pd.DataFrame) -> dict[str, float | None]:
    close = pd.to_numeric(df["close"], errors="coerce")
    volume = _numeric_series(df, "volume")
    amount = _numeric_series(df, "amount")
    last = df.iloc[-1] if not df.empty else {}
    vol_ma20 = volume.rolling(20).mean().iloc[-1] if len(volume) >= 20 else None
    return {
        "close": _float_or_none(last.get("close")),
        "pct_chg": _float_or_none(last.get("pct_chg")),
        "vol_ratio": _safe_ratio(_float_or_none(last.get("volume")), _float_or_none(vol_ma20)),
        "amount_avg_wan": _float_or_none(amount.tail(20).mean() / 10000) if not amount.empty else None,
        "ma50": _float_or_none(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None,
        "ma200": _float_or_none(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None,
    }


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def _float_or_none(value: Any) -> float | None:
    try:
        if pd.notna(value):
            return float(value)
    except (TypeError, ValueError):
        return None
    return None


def _safe_ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _l1_reason(spec: SymbolSpec, df: pd.DataFrame, ctx: ReplayContext, cfg: FunnelConfig) -> str:
    name = ctx.name_map.get(spec.symbol, "")
    if cfg.require_cn_main_or_chinext and spec.market == "cn" and not spec.symbol.startswith(("0", "3", "6")):
        return "非主板/创业板/科创板标的，不在 A 股漏斗股票池"
    if "ST" in name.upper():
        return "名称包含 ST，被 Layer1 硬过滤"
    avg_amount = _day_metrics(df)["amount_avg_wan"]
    cap = ctx.market_cap_map.get(spec.symbol)
    if cap is not None and cap < cfg.min_market_cap_yi:
        return f"总市值 {cap:.1f}亿低于阈值 {cfg.min_market_cap_yi:.1f}亿"
    if avg_amount is not None and avg_amount < cfg.min_avg_amount_wan:
        return f"20日均成交额 {avg_amount:.0f}万低于阈值 {cfg.min_avg_amount_wan:.0f}万"
    return "未通过 Layer1 硬过滤，通常是标的范围/成交额/市值条件不满足"


def _l2_reason(spec: SymbolSpec, df: pd.DataFrame, cfg: FunnelConfig) -> str:
    metrics = _day_metrics(df)
    if metrics["ma200"] is None:
        return "历史不足 200 日，主升/吸筹/RPS 等 Layer2 指标不完整"
    if metrics["close"] and metrics["ma50"] and metrics["close"] < metrics["ma50"]:
        return f"收盘 {metrics['close']:.2f} 低于 MA50 {metrics['ma50']:.2f}，强弱通道不足"
    if spec.market == "cn" and cfg.enable_rps_filter:
        return "未通过 Layer2 七通道，常见原因是 RPS/相对强弱或吸筹结构不足"
    return "未通过 Layer2 七通道（主升/潜伏/吸筹/地量/护盘/趋势延续/点火）"


def _l3_reason(spec: SymbolSpec, ctx: ReplayContext) -> str:
    sector = ctx.sector_map.get(spec.symbol, "")
    suffix = f"，当前行业/概念={sector}" if sector else ""
    return f"Layer3 板块/概念共振不足{suffix}"


def _l4_reason(df: pd.DataFrame) -> str:
    abc = _best_abc(df, [])
    return f"通过前置层，但未触发正式 Spring/SOS/LPS/EVR/Compression；ABC={abc['grade']}({abc['met_count']}/3)"


def _selected_reason(scores: dict[str, float], df: pd.DataFrame) -> str:
    abc = _best_abc(df, list(scores))
    labels = [f"{TRIGGER_LABELS.get(key, key)} {value:.2f}" for key, value in scores.items()]
    return f"触发 {' + '.join(labels)}；ABC={abc['grade']}({abc['met_count']}/3)"


def summarize_diagnostics(rows: list[DayDiagnostic]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        key = row.status if row.status == "SELECTED" else row.failed_layer
        counts[key] = counts.get(key, 0) + 1
    selected = [row for row in rows if row.status == "SELECTED"]
    return {
        "total_days": len(rows),
        "selected_days": len(selected),
        "counts": counts,
        "first_selected": selected[0].date if selected else None,
        "last_selected": selected[-1].date if selected else None,
    }


def write_outputs(
    output_dir: Path, spec: SymbolSpec, rows: list[DayDiagnostic], summary: dict[str, Any]
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "csv": output_dir / "daily_diagnostics.csv",
        "json": output_dir / "summary.json",
        "md": output_dir / "report.md",
    }
    _write_csv(paths["csv"], rows)
    paths["json"].write_text(
        json.dumps(_json_payload(spec, rows, summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["md"].write_text(build_report(spec, rows, summary), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def _write_csv(path: Path, rows: list[DayDiagnostic]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(rows[0]).keys()) if rows else ["date"])
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _json_payload(spec: SymbolSpec, rows: list[DayDiagnostic], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": asdict(spec),
        "summary": summary,
        "daily": [asdict(row) for row in rows],
        "note": "RPS 已基于全市场截面排名；板块热度无法完全等价于全市场生产任务。",
    }


def build_report(spec: SymbolSpec, rows: list[DayDiagnostic], summary: dict[str, Any]) -> str:
    lines = [
        f"# 单票漏斗复盘诊断：{spec.symbol}",
        "",
        f"- 市场: {spec.label}",
        f"- 回放交易日: {summary['total_days']}",
        f"- 被漏斗选中: {summary['selected_days']}",
        f"- 首次/最后选中: {summary['first_selected'] or '-'} / {summary['last_selected'] or '-'}",
        f"- 层级分布: {_fmt_counts(summary['counts'])}",
        "",
        "> 注：RPS 已基于全市场截面排名（主板+创业板+科创板）；板块热度属于全市场依赖，报告中按单票上下文近似。",
        "",
        "## 每日明细",
        "",
        "| 日期 | 结果 | 卡点 | 触发 | ABC | 收盘 | 涨跌幅 | 量比 | 原因 |",
        "|---|---:|---:|---|---:|---:|---:|---:|---|",
    ]
    lines.extend(_report_row(row) for row in rows)
    return "\n".join(lines) + "\n"


def _report_row(row: DayDiagnostic) -> str:
    return (
        f"| {row.date} | {row.status} | {row.failed_layer} | {row.triggers} | "
        f"{row.abc_grade} | {_fmt(row.close)} | {_fmt(row.pct_chg, suffix='%')} | "
        f"{_fmt(row.vol_ratio, digits=2, suffix='x')} | {row.reason} |"
    )


def _fmt(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    return "-" if value is None else f"{value:.{digits}f}{suffix}"


def _fmt_counts(counts: dict[str, int]) -> str:
    return " / ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "-"


def notify_feishu(spec: SymbolSpec, summary: dict[str, Any], report_path: str) -> None:
    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    run_url = os.getenv("GITHUB_RUN_URL", "").strip()
    content = "\n".join(
        [
            f"单票漏斗复盘：{spec.symbol}（{spec.label}）",
            f"- 回放交易日: {summary['total_days']}",
            f"- 被选中: {summary['selected_days']}",
            f"- 首次/最后选中: {summary['first_selected'] or '-'} / {summary['last_selected'] or '-'}",
            f"- 层级分布: {_fmt_counts(summary['counts'])}",
            f"- 报告文件: {report_path}",
            f"- Actions: {run_url or '-'}",
        ]
    )
    send_feishu_notification(webhook, f"单票漏斗复盘 {spec.symbol}", content)


def _parse_symbols(raw: str) -> list[SymbolSpec]:
    parts = [s.strip() for s in raw.replace(";", ",").split(",") if s.strip()]
    if not parts:
        raise ValueError("symbol 不能为空")
    specs = [detect_symbol_market(p) for p in parts]
    markets = {s.market for s in specs}
    if len(markets) > 1:
        raise ValueError(f"批量模式要求所有股票属于同一市场，当前包含: {', '.join(sorted(markets))}")
    return specs


def _run_single(
    spec: SymbolSpec,
    start: date,
    end: date,
    trading_days: int,
    output_dir: Path,
    rps_histories: dict[str, pd.DataFrame] | None,
) -> int:
    print(f"[diagnosis] symbol={spec.symbol} market={spec.market} range={start}~{end}", flush=True)
    hist = fetch_symbol_history(spec, start, end, trading_days)
    if hist.empty:
        print(f"[diagnosis] {spec.symbol} 没有获取到可用历史数据，跳过", flush=True)
        return 1
    ctx = build_context(spec, hist, start, end)
    cfg = config_for_symbol(spec, trading_days)
    rows = replay_symbol(spec, hist, ctx, cfg, start, end, rps_histories)
    summary = summarize_diagnostics(rows)
    paths = write_outputs(output_dir, spec, rows, summary)
    notify_feishu(spec, summary, paths["md"])
    print(f"[diagnosis] done {spec.symbol} selected={summary['selected_days']} report={paths['md']}", flush=True)
    return 0


def run(args: argparse.Namespace) -> int:
    start = parse_ymd(args.start_date)
    end = parse_ymd(args.end_date)
    if end < start:
        raise ValueError("end-date 不能早于 start-date")
    specs = _parse_symbols(args.symbol)
    cfg = config_for_symbol(specs[0], int(args.trading_days))
    rps_histories = _load_rps_histories(specs[0], start, end, cfg, getattr(args, "skip_rps_universe", False))
    failed = 0
    base_dir = Path(args.output_dir)
    for spec in specs:
        out_dir = base_dir / spec.symbol if len(specs) > 1 else base_dir
        failed += _run_single(spec, start, end, int(args.trading_days), out_dir, rps_histories)
    return min(failed, 1)


def _load_rps_histories(
    spec: SymbolSpec, start: date, end: date, cfg: FunnelConfig, skip_rps: bool
) -> dict[str, pd.DataFrame] | None:
    if skip_rps or spec.market != "cn" or not cfg.enable_rps_filter:
        return None
    histories = load_rps_universe_histories(spec, start, end, cfg.rps_window_slow + 30)
    if len(histories) < MIN_RPS_UNIVERSE_HISTORIES:
        raise RuntimeError(
            f"RPS 全市场历史不足（{len(histories)}/{MIN_RPS_UNIVERSE_HISTORIES}），"
            "无法生成可信截面排名；如需快速近似请显式使用 --skip-rps-universe"
        )
    return histories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="单只股票漏斗逐日复盘诊断")
    parser.add_argument("--symbol", required=True, help="股票代码，逗号分隔可批量，同一市场，如 002980,301511,301018")
    parser.add_argument("--start-date", required=True, help="回看起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="回看结束日期 YYYY-MM-DD")
    parser.add_argument("--trading-days", type=int, default=320, help="起始日前置交易日数量")
    parser.add_argument("--output-dir", default="logs/single_symbol_funnel", help="输出目录")
    parser.add_argument("--skip-rps-universe", action="store_true", help="跳过全市场 RPS 计算（快速模式，RPS 不准确）")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
