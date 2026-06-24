"""K-line quality checks for Wyckoff pipelines."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class KlineIssue:
    severity: str
    category: str
    message: str
    count: int = 0


@dataclass(frozen=True)
class KlineQualityReport:
    symbol: str
    rows: int
    ok: bool
    score: float
    issues: tuple[KlineIssue, ...]


REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume")


def _issue(severity: str, category: str, message: str, count: int = 0) -> KlineIssue:
    return KlineIssue(severity=severity, category=category, message=message, count=int(count))


def check_kline_quality(
    df: pd.DataFrame | None,
    *,
    symbol: str = "",
    required_columns: Iterable[str] = REQUIRED_COLUMNS,
    extreme_pct_threshold: float = 0.22,
) -> KlineQualityReport:
    """Run lightweight OHLCV quality checks.

    This is intentionally small and dependency-free so it can run inside daily
    jobs before strategy logic.  It reports problems instead of mutating data.
    """

    symbol_s = str(symbol or "").strip()
    if df is None:
        return _quality_report(symbol_s, 0, (_issue("error", "missing_frame", "K线数据为空"),))
    rows = int(len(df))
    if df.empty:
        return _quality_report(symbol_s, 0, (_issue("error", "empty_frame", "K线数据无记录"),))

    numeric = _numeric_series(df)
    issues = [
        *_required_column_issues(df, required_columns),
        *_numeric_issues(numeric),
        *_date_issues(df),
        *_ohlc_issues(numeric, extreme_pct_threshold),
        *_volume_issues(numeric),
    ]
    return _quality_report(symbol_s, rows, tuple(issues))


def _quality_report(symbol: str, rows: int, issues: tuple[KlineIssue, ...]) -> KlineQualityReport:
    error_count = sum(1 for item in issues if item.severity == "error")
    warning_count = sum(1 for item in issues if item.severity == "warning")
    score = max(0.0, 100.0 - error_count * 25.0 - warning_count * 8.0)
    return KlineQualityReport(
        symbol=symbol,
        rows=rows,
        ok=error_count == 0,
        score=float(score),
        issues=issues,
    )


def _required_column_issues(df: pd.DataFrame, required_columns: Iterable[str]) -> list[KlineIssue]:
    missing_cols = [col for col in required_columns if col not in df.columns]
    if not missing_cols:
        return []
    return [_issue("error", "missing_columns", f"缺少字段: {', '.join(missing_cols)}", len(missing_cols))]


def _numeric_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    columns = [col for col in ("open", "high", "low", "close", "volume", "amount") if col in df.columns]
    return {col: pd.to_numeric(df[col], errors="coerce") for col in columns}


def _numeric_issues(numeric: dict[str, pd.Series]) -> list[KlineIssue]:
    issues = []
    for col, series in numeric.items():
        missing_count = int(series.isna().sum())
        if not missing_count:
            continue
        severity = "error" if col in {"open", "high", "low", "close"} else "warning"
        issues.append(_issue(severity, "numeric_missing", f"{col} 存在非数值或缺失", missing_count))
    return issues


def _date_issues(df: pd.DataFrame) -> list[KlineIssue]:
    if "date" not in df.columns:
        return []
    issues = []
    dt = pd.to_datetime(df["date"], errors="coerce")
    bad_dates = int(dt.isna().sum())
    if bad_dates:
        issues.append(_issue("error", "bad_date", "date 存在无法解析的日期", bad_dates))
    valid_dt = dt.dropna()
    if not valid_dt.empty and not valid_dt.is_monotonic_increasing:
        issues.append(_issue("error", "date_order", "date 不是升序排列"))
    duplicated = int(dt.duplicated().sum())
    if duplicated:
        issues.append(_issue("error", "duplicate_date", "date 存在重复记录", duplicated))
    return issues


def _ohlc_issues(numeric: dict[str, pd.Series], extreme_pct_threshold: float) -> list[KlineIssue]:
    if not {"open", "high", "low", "close"}.issubset(numeric):
        return []
    open_s, high_s, low_s, close_s = numeric["open"], numeric["high"], numeric["low"], numeric["close"]
    issues = []
    bad_price = ((open_s <= 0) | (high_s <= 0) | (low_s <= 0) | (close_s <= 0)).fillna(False)
    if int(bad_price.sum()):
        issues.append(_issue("error", "non_positive_price", "OHLC 存在非正价格", int(bad_price.sum())))
    bad_ohlc = (
        (high_s < low_s) | (high_s < open_s) | (high_s < close_s) | (low_s > open_s) | (low_s > close_s)
    ).fillna(False)
    if int(bad_ohlc.sum()):
        issues.append(_issue("error", "ohlc_inconsistent", "OHLC 高低价关系不合理", int(bad_ohlc.sum())))
    extreme = int((close_s.pct_change().abs() > float(extreme_pct_threshold)).sum())
    if extreme:
        issues.append(_issue("warning", "extreme_return", "相邻收盘涨跌幅异常偏大", extreme))
    return issues


def _volume_issues(numeric: dict[str, pd.Series]) -> list[KlineIssue]:
    if "volume" not in numeric:
        return []
    negative_volume = int((numeric["volume"] < 0).sum())
    if not negative_volume:
        return []
    return [_issue("error", "negative_volume", "成交量存在负数", negative_volume)]


def check_kline_quality_map(df_map: dict[str, pd.DataFrame]) -> dict[str, KlineQualityReport]:
    return {str(symbol): check_kline_quality(df, symbol=str(symbol)) for symbol, df in (df_map or {}).items()}


def summarize_quality_reports(reports: dict[str, KlineQualityReport]) -> dict[str, object]:
    total = len(reports or {})
    error_symbols = [symbol for symbol, report in reports.items() if any(x.severity == "error" for x in report.issues)]
    warning_symbols = [
        symbol
        for symbol, report in reports.items()
        if symbol not in set(error_symbols) and any(x.severity == "warning" for x in report.issues)
    ]
    issue_counts: dict[str, int] = {}
    for report in reports.values():
        for issue in report.issues:
            issue_counts[issue.category] = issue_counts.get(issue.category, 0) + max(issue.count, 1)
    return {
        "total": total,
        "ok": max(total - len(error_symbols), 0),
        "error_symbols": len(error_symbols),
        "warning_symbols": len(warning_symbols),
        "issue_counts": issue_counts,
        "sample_error_symbols": error_symbols[:8],
        "sample_warning_symbols": warning_symbols[:8],
    }


__all__ = [
    "KlineIssue",
    "KlineQualityReport",
    "check_kline_quality",
    "check_kline_quality_map",
    "summarize_quality_reports",
]
