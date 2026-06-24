"""Tushare stock-history provider."""

from __future__ import annotations

import logging

import pandas as pd

from integrations.data_source_format import STOCK_HIST_COLUMNS, to_ts_code

logger = logging.getLogger(__name__)


def fetch_stock_tushare(symbol: str, start: str, end: str) -> pd.DataFrame:
    from integrations.tushare_client import get_pro, wait_for_rate_limit

    pro = get_pro()
    if pro is None:
        raise RuntimeError("token_missing")

    import tushare as ts

    wait_for_rate_limit()
    ts_code = to_ts_code(symbol)
    df = ts.pro_bar(ts_code=ts_code, adj="qfq", start_date=start, end_date=end)
    if df is None or df.empty:
        _raise_tushare_empty(pro, ts_code, start, end)
    return _normalize_tushare_frame(df)


def _raise_tushare_empty(pro, ts_code: str, start: str, end: str) -> None:
    try:
        df_no_adj = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
    except Exception:
        logger.debug("tushare qfq diagnosis probe failed", exc_info=True)
        raise RuntimeError("tushare empty") from None
    if df_no_adj is not None and not df_no_adj.empty:
        raise RuntimeError("tushare empty (qfq auth limit?)")
    raise RuntimeError("tushare empty")


def _normalize_tushare_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(
        columns={
            "trade_date": "日期",
            "open": "开盘",
            "high": "最高",
            "low": "最低",
            "close": "收盘",
            "vol": "成交量",
            "amount": "成交额",
            "pct_chg": "涨跌幅",
        }
    )
    out["成交量"] = pd.to_numeric(out["成交量"], errors="coerce") * 100
    out["成交额"] = pd.to_numeric(out["成交额"], errors="coerce") * 1000
    out["换手率"] = pd.NA
    out["振幅"] = pd.NA
    dates = out["日期"].astype(str)
    out["日期"] = dates.str[:4] + "-" + dates.str[4:6] + "-" + dates.str[6:8]
    return out[list(STOCK_HIST_COLUMNS)].copy()
