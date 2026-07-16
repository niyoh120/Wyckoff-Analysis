"""A-share CSV export workflow."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from integrations.fetch_a_share_csv import (
    TradingWindow,
    fetch_hist,
    get_all_stocks,
    normalize_symbols,
    resolve_trading_window,
)
from utils.helpers import extract_symbols_from_text, safe_filename_part, stock_sector_em

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportAShareCsvRequest:
    symbol: str = ""
    symbols: tuple[str, ...] = field(default_factory=tuple)
    symbols_text: str = ""
    trading_days: int = 320
    end_offset_days: int = 1
    adjust: str = ""
    out_dir: str = "data"


def run_export_a_share_csv(request: ExportAShareCsvRequest) -> int:
    code_to_name = load_code_name_map()
    symbols = resolve_export_symbols(request, valid_codes=set(code_to_name))
    end_calendar = date.today() - timedelta(days=int(request.end_offset_days))
    window = resolve_trading_window(end_calendar_day=end_calendar, trading_days=int(request.trading_days))
    out_dir = os.path.abspath(request.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    logger.info(
        "trade_window=%s..%s (trading_days=%s)", window.start_trade_date, window.end_trade_date, request.trading_days
    )
    return 1 if write_export_batch(request, symbols, code_to_name, window, out_dir) else 0


def build_export_frame(df: pd.DataFrame, sector: str) -> pd.DataFrame:
    required = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "换手率", "振幅"]
    out = df.copy()
    for col in required:
        if col not in out.columns:
            out[col] = pd.NA
    out = out[required].copy()
    for col in ["成交量", "成交额"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["AvgPrice"] = out["成交额"] / out["成交量"].replace(0, pd.NA)
    out["Sector"] = sector
    out = out.rename(
        columns={
            "日期": "Date",
            "开盘": "Open",
            "最高": "High",
            "最低": "Low",
            "收盘": "Close",
            "成交量": "Volume",
            "成交额": "Amount",
            "换手率": "TurnoverRate",
            "振幅": "Amplitude",
        }
    )
    return out[
        ["Date", "Open", "High", "Low", "Close", "Volume", "Amount", "TurnoverRate", "Amplitude", "AvgPrice", "Sector"]
    ]


def load_code_name_map() -> dict[str, str]:
    stocks = get_all_stocks()
    mapping = {str(row.get("code", "")).strip(): str(row.get("name", "")).strip() for row in stocks}
    mapping = {code: name for code, name in mapping.items() if code and name}
    if not mapping:
        raise RuntimeError("stock_info_a_code_name empty")
    return mapping


def resolve_export_symbols(request: ExportAShareCsvRequest, valid_codes: set[str]) -> list[str]:
    candidates: list[str] = []
    if request.symbol:
        candidates.append(request.symbol)
    if request.symbols:
        candidates.extend(request.symbols)
    if request.symbols_text:
        candidates.extend(extract_symbols_from_text(request.symbols_text, valid_codes=valid_codes))
    symbols = normalize_symbols(candidates)
    if not symbols:
        raise SystemExit("请提供股票代码：--symbol 或 --symbols 或 --symbols-text")
    return symbols


def write_export_batch(
    request: ExportAShareCsvRequest,
    symbols: list[str],
    code_to_name: dict[str, str],
    window: TradingWindow,
    out_dir: str,
) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    for symbol in symbols:
        try:
            write_symbol_export(symbol, request, code_to_name, window, out_dir)
        except Exception as exc:
            failures.append((symbol, str(exc)))
            logger.warning("FAIL symbol=%s err=%s", symbol, exc)
    return failures


def write_symbol_export(
    symbol: str,
    request: ExportAShareCsvRequest,
    code_to_name: dict[str, str],
    window: TradingWindow,
    out_dir: str,
) -> tuple[str, str]:
    name = code_to_name.get(symbol)
    if not name:
        raise RuntimeError(f"symbol not found in stock list: {symbol}")
    df_hist = fetch_hist(symbol=symbol, window=window, adjust=str(request.adjust))
    hist_path, ohlcv_path = write_two_csv(symbol, name, df_hist, out_dir, stock_sector_em(symbol))
    logger.info(
        "OK symbol=%s name=%s -> %s, %s", symbol, name, os.path.basename(hist_path), os.path.basename(ohlcv_path)
    )
    return hist_path, ohlcv_path


def write_two_csv(symbol: str, name: str, df_hist: pd.DataFrame, out_dir: str, sector: str) -> tuple[str, str]:
    file_prefix = f"{safe_filename_part(symbol, fallback='')}_{safe_filename_part(name, fallback='')}"
    hist_path = os.path.join(out_dir, f"{file_prefix}_hist_data.csv")
    ohlcv_path = os.path.join(out_dir, f"{file_prefix}_ohlcv.csv")
    df_hist.to_csv(hist_path, index=False, encoding="utf-8-sig")
    build_export_frame(df_hist, sector=sector).to_csv(ohlcv_path, index=False, encoding="utf-8-sig")
    return hist_path, ohlcv_path
