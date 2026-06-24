"""
参数敏感性分析 (Grid Search)

遍历 hold_days × stop_loss × take_profit × top_n 的参数空间，
调用 workflows.backtest.run_backtest_request() 各跑一轮，
输出 CSV heatmap + 最优参数组合 markdown。

用法:
    python -m scripts.param_sensitivity \
        --start 2025-09-01 --end 2026-02-28 \
        --snapshot-dir data/backtest_snapshots/20260301 \
        --output-dir analysis/sensitivity
"""

from __future__ import annotations

import itertools
import json
import os
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.backtest_run import parse_date
from workflows.backtest import BacktestWorkflowRequest, run_backtest_request

# ── 默认参数空间（可通过环境变量 JSON 覆盖） ──

DEFAULT_HOLD_DAYS_GRID = [15, 30, 45, 60]
DEFAULT_STOP_LOSS_GRID = [0.0, -5.0, -8.0, -12.0]  # 0 = 不设止损
DEFAULT_TAKE_PROFIT_GRID = [0.0, 8.0, 15.0, 25.0]  # 0 = 不设止盈
DEFAULT_TRAILING_STOP_GRID = [0.0, -5.0, -8.0, -12.0]  # 0 = 不启用移动止盈
DEFAULT_TRAILING_ACTIVATE_GRID = [0.0, 10.0, 15.0]  # 移动止盈激活门槛(%)
DEFAULT_TOP_N_GRID = [3, 5, 8]


@dataclass(frozen=True)
class SensitivityCombo:
    hold_days: int
    stop_loss_pct: float
    take_profit_pct: float
    trailing_stop_pct: float
    trailing_activate_pct: float
    top_n: int

    @property
    def label(self) -> str:
        return (
            f"hd={self.hold_days}_sl={self.stop_loss_pct}_tp={self.take_profit_pct}_"
            f"ts={self.trailing_stop_pct}_ta={self.trailing_activate_pct}_tn={self.top_n}"
        )


@dataclass(frozen=True)
class SensitivityRunConfig:
    start_dt: object
    end_dt: object
    board: str
    sample_size: int
    trading_days: int
    max_workers: int
    snapshot_dir: Path | None
    exit_mode: str


@dataclass(frozen=True)
class ParamSensitivityRequest:
    start: str
    end: str
    board: str = "all"
    sample_size: int = 300
    trading_days: int = 320
    workers: int = 8
    snapshot_dir: str = ""
    output_dir: str = "analysis/sensitivity"
    exit_mode: str = "sltp"


def run_param_sensitivity_request(request: ParamSensitivityRequest) -> int:
    snapshot = Path(request.snapshot_dir).resolve() if request.snapshot_dir.strip() else None
    result_df = run_sensitivity(
        parse_date(request.start),
        parse_date(request.end),
        board=request.board,
        sample_size=request.sample_size,
        trading_days=request.trading_days,
        max_workers=request.workers,
        snapshot_dir=snapshot,
        exit_mode=request.exit_mode,
    )
    csv_path, md_path = _sensitivity_output_paths(Path(request.output_dir).resolve())
    result_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    md_content = build_sensitivity_markdown(result_df)
    md_path.write_text(md_content + "\n", encoding="utf-8")

    print(f"\n[sensitivity] CSV -> {csv_path}")
    print(f"[sensitivity] MD  -> {md_path}")
    print(md_content)
    return 0


def _sensitivity_output_paths(out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"sensitivity_{stamp}.csv", out_dir / f"sensitivity_{stamp}.md"


def _load_grid(env_key: str, default: list) -> list:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default
    from contextlib import suppress

    with suppress(Exception):
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    return default


def _resolve_sensitivity_grids(
    hold_days_grid: list[int] | None,
    stop_loss_grid: list[float] | None,
    take_profit_grid: list[float] | None,
    trailing_stop_grid: list[float] | None,
    trailing_activate_grid: list[float] | None,
    top_n_grid: list[int] | None,
) -> tuple[list, list, list, list, list, list]:
    return (
        hold_days_grid or _load_grid("SENSITIVITY_HOLD_DAYS", DEFAULT_HOLD_DAYS_GRID),
        stop_loss_grid or _load_grid("SENSITIVITY_STOP_LOSS", DEFAULT_STOP_LOSS_GRID),
        take_profit_grid or _load_grid("SENSITIVITY_TAKE_PROFIT", DEFAULT_TAKE_PROFIT_GRID),
        trailing_stop_grid or _load_grid("SENSITIVITY_TRAILING_STOP", DEFAULT_TRAILING_STOP_GRID),
        trailing_activate_grid or _load_grid("SENSITIVITY_TRAILING_ACTIVATE", DEFAULT_TRAILING_ACTIVATE_GRID),
        top_n_grid or _load_grid("SENSITIVITY_TOP_N", DEFAULT_TOP_N_GRID),
    )


def _build_sensitivity_combos(grids: tuple[list, list, list, list, list, list]) -> list[SensitivityCombo]:
    return [
        SensitivityCombo(int(hd), float(sl), float(tp), float(ts), float(ta), int(tn))
        for hd, sl, tp, ts, ta, tn in itertools.product(*grids)
    ]


def _summary_to_row(combo: SensitivityCombo, summary: dict) -> dict:
    row = {
        "hold_days": combo.hold_days,
        "stop_loss_pct": combo.stop_loss_pct,
        "take_profit_pct": combo.take_profit_pct,
        "trailing_stop_pct": combo.trailing_stop_pct,
        "trailing_activate_pct": combo.trailing_activate_pct,
        "top_n": combo.top_n,
        "trades": summary.get("trades", 0),
        "win_rate_pct": summary.get("win_rate_pct"),
        "avg_ret_pct": summary.get("avg_ret_pct"),
        "median_ret_pct": summary.get("median_ret_pct"),
        "max_drawdown_pct": summary.get("max_drawdown_pct"),
        "sharpe_ratio": summary.get("sharpe_ratio"),
        "calmar_ratio": summary.get("calmar_ratio"),
        "var95_ret_pct": summary.get("var95_ret_pct"),
        "cvar95_ret_pct": summary.get("cvar95_ret_pct"),
        "max_consecutive_losses": summary.get("max_consecutive_losses"),
    }
    strat = summary.get("stratified", {})
    for track in ["Trend", "Accum"]:
        track_stats = strat.get("by_track", {}).get(track, {})
        row[f"{track}_trades"] = track_stats.get("trades", 0)
        row[f"{track}_win_rate"] = track_stats.get("win_rate_pct")
        row[f"{track}_avg_ret"] = track_stats.get("avg_ret_pct")
        row[f"{track}_sharpe"] = track_stats.get("sharpe_ratio")
    return row


def _error_row(combo: SensitivityCombo, exc: Exception) -> dict:
    return {
        "hold_days": combo.hold_days,
        "stop_loss_pct": combo.stop_loss_pct,
        "take_profit_pct": combo.take_profit_pct,
        "trailing_stop_pct": combo.trailing_stop_pct,
        "trailing_activate_pct": combo.trailing_activate_pct,
        "top_n": combo.top_n,
        "trades": 0,
        "error": str(exc),
    }


def _run_sensitivity_combo(config: SensitivityRunConfig, combo: SensitivityCombo) -> dict:
    _, summary = run_backtest_request(
        BacktestWorkflowRequest(
            start_dt=config.start_dt,
            end_dt=config.end_dt,
            hold_days=combo.hold_days,
            top_n=combo.top_n,
            board=config.board,
            sample_size=config.sample_size,
            trading_days=config.trading_days,
            max_workers=config.max_workers,
            snapshot_dir=config.snapshot_dir,
            exit_mode=config.exit_mode,
            stop_loss_pct=combo.stop_loss_pct,
            take_profit_pct=combo.take_profit_pct,
            trailing_stop_pct=combo.trailing_stop_pct,
            trailing_activate_pct=combo.trailing_activate_pct,
        )
    )
    return _summary_to_row(combo, summary)


def run_sensitivity(
    start_dt,
    end_dt,
    *,
    board: str = "all",
    sample_size: int = 300,
    trading_days: int = 320,
    max_workers: int = 8,
    snapshot_dir: Path | None = None,
    hold_days_grid: list[int] | None = None,
    stop_loss_grid: list[float] | None = None,
    take_profit_grid: list[float] | None = None,
    trailing_stop_grid: list[float] | None = None,
    trailing_activate_grid: list[float] | None = None,
    top_n_grid: list[int] | None = None,
    exit_mode: str = "sltp",
) -> pd.DataFrame:
    """遍历参数空间并返回汇总 DataFrame。"""

    grids = _resolve_sensitivity_grids(
        hold_days_grid,
        stop_loss_grid,
        take_profit_grid,
        trailing_stop_grid,
        trailing_activate_grid,
        top_n_grid,
    )
    combos = _build_sensitivity_combos(grids)
    print(
        f"[sensitivity] 参数空间: {len(grids[0])}×{len(grids[1])}×{len(grids[2])}×"
        f"{len(grids[3])}×{len(grids[4])}×{len(grids[5])} = {len(combos)} 组合"
    )
    config = SensitivityRunConfig(
        start_dt, end_dt, board, sample_size, trading_days, max_workers, snapshot_dir, exit_mode
    )

    rows: list[dict] = []
    for idx, combo in enumerate(combos, 1):
        print(f"\n[sensitivity] ({idx}/{len(combos)}) {combo.label}")
        try:
            row = _run_sensitivity_combo(config, combo)
            rows.append(row)
            print(
                f"  -> trades={row['trades']}, win={row.get('win_rate_pct', '-')}%, sharpe={row.get('sharpe_ratio', '-')}"
            )
        except Exception as exc:
            print(f"  -> FAILED: {exc}")
            traceback.print_exc()
            rows.append(_error_row(combo, exc))

    return pd.DataFrame(rows)


def build_sensitivity_markdown(df: pd.DataFrame) -> str:
    lines = [
        "# 参数敏感性分析结果",
        "",
        f"- 参数组合总数: {len(df)}",
        f"- 有效组合数: {len(df[df['trades'] > 0])}",
        "",
    ]

    valid = df[df["trades"] > 0].copy()
    if valid.empty:
        lines.append("⚠️ 无有效回测结果")
        return "\n".join(lines)

    sharpe_col = pd.to_numeric(valid.get("sharpe_ratio"), errors="coerce")
    if sharpe_col.notna().any():
        lines.extend(_best_sharpe_lines(valid, sharpe_col))
        lines.extend(_top_sharpe_lines(valid))
    lines.extend(_dimension_sensitivity_lines(valid))
    return "\n".join(lines)


def _best_sharpe_lines(valid: pd.DataFrame, sharpe_col: pd.Series) -> list[str]:
    best = valid.loc[sharpe_col.idxmax()]
    return [
        "## 最优参数（按夏普比）",
        "",
        f"- hold_days: **{int(best['hold_days'])}**",
        f"- stop_loss: **{best['stop_loss_pct']}%**",
        f"- take_profit: **{best['take_profit_pct']}%**",
        f"- trailing_stop: **{best.get('trailing_stop_pct', 0)}%**",
        f"- trailing_activate: **{best.get('trailing_activate_pct', 0)}%**",
        f"- top_n: **{int(best['top_n'])}**",
        f"- 夏普比: **{best.get('sharpe_ratio', '-')}**",
        f"- 胜率: {best.get('win_rate_pct', '-')}%",
        f"- 平均收益: {best.get('avg_ret_pct', '-')}%",
        f"- 最大回撤: {best.get('max_drawdown_pct', '-')}%",
        "",
    ]


def _top_sharpe_lines(valid: pd.DataFrame) -> list[str]:
    lines = ["## Top 10 参数组合（按夏普比）", ""]
    lines.append("| 排名 | hold | SL | TP | topN | 笔数 | 胜率 | 均收 | 夏普 | 卡玛 | MDD |")
    lines.append("|------|------|-----|-----|------|------|------|------|------|------|------|")
    for rank, (_, row) in enumerate(valid.nlargest(10, "sharpe_ratio").iterrows(), 1):
        lines.append(_top_sharpe_row(rank, row))
    lines.append("")
    return lines


def _top_sharpe_row(rank: int, row: pd.Series) -> str:
    return (
        f"| {rank} | {int(row['hold_days'])} | {row['stop_loss_pct']} | {row['take_profit_pct']} "
        f"| {int(row['top_n'])} | {int(row['trades'])} | {_fmt_optional(row.get('win_rate_pct'))} "
        f"| {_fmt_optional(row.get('avg_ret_pct'), 3)} | {_fmt_optional(row.get('sharpe_ratio'), 3)} "
        f"| {_fmt_optional(row.get('calmar_ratio'), 3)} | {_fmt_optional(row.get('max_drawdown_pct'), 3)} |"
    )


def _dimension_sensitivity_lines(valid: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    for dim_name, dim_col in [
        ("hold_days", "hold_days"),
        ("stop_loss_pct", "stop_loss_pct"),
        ("take_profit_pct", "take_profit_pct"),
        ("top_n", "top_n"),
    ]:
        if dim_col not in valid.columns:
            continue
        grouped = (
            valid.groupby(dim_col)
            .agg(
                trades=("trades", "sum"),
                avg_sharpe=("sharpe_ratio", "mean"),
                avg_win_rate=("win_rate_pct", "mean"),
                avg_ret=("avg_ret_pct", "mean"),
            )
            .reset_index()
        )
        lines.extend([f"## 敏感性：{dim_name}", ""])
        lines.append(f"| {dim_name} | 总笔数 | 平均夏普 | 平均胜率 | 平均收益 |")
        lines.append("|----------|--------|---------|---------|---------|")
        for _, r in grouped.iterrows():
            lines.append(
                f"| {r[dim_col]} | {int(r['trades'])} | {_fmt_optional(r.get('avg_sharpe'))} "
                f"| {_fmt_optional(r.get('avg_win_rate'), 2)} | {_fmt_optional(r.get('avg_ret'))} |"
            )
        lines.append("")
    return lines


def _fmt_optional(value, digits: int = 2) -> str:
    return f"{value:.{digits}f}" if pd.notna(value) else "-"
