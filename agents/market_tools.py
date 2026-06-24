from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

from agents.tool_context import ToolContext, ensure_tushare_token, get_credential

logger = logging.getLogger(__name__)

MARKET_OVERVIEW_INDICES = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000016.SH": "上证50",
    "000905.SH": "中证500",
}
MARKET_HISTORY_INDEXES = {
    "sse": ("000001.SH", "上证指数"),
    "csi300": ("000300.SH", "沪深300"),
    "szse": ("399001.SZ", "深证成指"),
    "chinext": ("399006.SZ", "创业板指"),
    "sse50": ("000016.SH", "上证50"),
    "csi500": ("000905.SH", "中证500"),
}
MARKET_HISTORY_ALIASES = {
    "sh": "sse",
    "上证": "sse",
    "上证指数": "sse",
    "沪指": "sse",
    "沪深300": "csi300",
    "300": "csi300",
    "sz": "szse",
    "深证": "szse",
    "深成指": "szse",
    "深证成指": "szse",
    "创业板": "chinext",
    "创业板指": "chinext",
    "上证50": "sse50",
    "中证500": "csi500",
}


def get_market_overview(tool_context: ToolContext | None = None) -> dict:
    try:
        errors: list[str] = []
        tushare_result = _fetch_tushare_overview(tool_context, errors)
        if tushare_result:
            return {"indices": tushare_result, "source": "tushare"}
        akshare_result = _fetch_akshare_overview(errors)
        if akshare_result:
            return {"indices": akshare_result, "source": "akshare"}
        return {"error": "无法获取大盘数据", "details": "; ".join(errors) if errors else "unknown"}
    except Exception as e:
        logger.exception("get_market_overview error")
        return {"error": str(e)}


def _fetch_tushare_overview(tool_context: ToolContext | None, errors: list[str]) -> dict[str, dict] | None:
    try:
        ensure_tushare_token(tool_context)
        from integrations.tushare_client import get_pro

        pro = get_pro()
        if pro is None:
            errors.append("tushare: token 未配置或 client 不可用")
            return None
        end_date = date.today().strftime("%Y%m%d")
        start_date = (date.today() - timedelta(days=10)).strftime("%Y%m%d")
        return _tushare_index_rows(pro, start_date, end_date)
    except Exception as e:
        errors.append(f"tushare: {e}")
        return None


def _tushare_index_rows(pro, start_date: str, end_date: str) -> dict[str, dict]:
    result = {}
    for ts_code, name in MARKET_OVERVIEW_INDICES.items():
        try:
            df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                result[name] = _tushare_latest_row(ts_code, df)
        except Exception as e:
            result[name] = {"error": str(e)}
    return result


def _tushare_latest_row(ts_code: str, df) -> dict:
    latest = df.sort_values("trade_date").iloc[-1]
    return {
        "ts_code": ts_code,
        "trade_date": str(latest.get("trade_date", "")),
        "close": round(float(latest.get("close", 0)), 2),
        "pct_chg": round(float(latest.get("pct_chg", 0)), 2),
        "vol": int(latest.get("vol", 0)),
        "amount": round(float(latest.get("amount", 0)), 2),
    }


def _fetch_akshare_overview(errors: list[str]) -> dict[str, dict] | None:
    try:
        import akshare as ak

        spot = ak.stock_zh_index_spot_em()
        if spot is None or spot.empty:
            errors.append("akshare: stock_zh_index_spot_em 返回空")
            return None
        columns = _akshare_columns(spot)
        if not columns["code"]:
            errors.append("akshare: 缺少指数代码列")
            return None
        result = _akshare_index_rows(spot, columns)
        if result:
            return result
        errors.append("akshare: 目标指数未命中")
        return None
    except Exception as e:
        errors.append(f"akshare: {e}")
        return None


def _akshare_columns(spot) -> dict[str, str]:
    return {
        "code": _first_column(spot, ("代码", "指数代码")),
        "name": _first_column(spot, ("名称", "指数名称")),
        "close": _first_column(spot, ("最新价", "最新")),
        "pct": _first_column(spot, ("涨跌幅", "涨跌幅(%)")),
        "vol": _first_column(spot, ("成交量",)),
        "amount": _first_column(spot, ("成交额",)),
    }


def _first_column(df, candidates: tuple[str, ...]) -> str:
    return next((col for col in candidates if col in df.columns), "")


def _akshare_index_rows(spot, columns: dict[str, str]) -> dict[str, dict]:
    code_to_ts = {symbol.split(".", 1)[0]: symbol for symbol in MARKET_OVERVIEW_INDICES}
    result: dict[str, dict] = {}
    for _, row in spot.iterrows():
        code = "".join(ch for ch in str(row.get(columns["code"], "") or "").strip() if ch.isdigit())[-6:]
        if code not in code_to_ts:
            continue
        ts_code = code_to_ts[code]
        name = str(row.get(columns["name"], "") or "").strip() or MARKET_OVERVIEW_INDICES[ts_code]
        result[name] = _akshare_latest_row(ts_code, row, columns)
    return result


def _akshare_latest_row(ts_code: str, row, columns: dict[str, str]) -> dict:
    return {
        "ts_code": ts_code,
        "trade_date": date.today().strftime("%Y%m%d"),
        "close": round(_safe_float(row.get(columns["close"], 0) if columns["close"] else 0), 2),
        "pct_chg": round(_safe_float(row.get(columns["pct"], 0) if columns["pct"] else 0), 2),
        "vol": int(_safe_float(row.get(columns["vol"], 0) if columns["vol"] else 0)),
        "amount": round(_safe_float(row.get(columns["amount"], 0) if columns["amount"] else 0), 2),
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def resolve_market_history_index(index: str) -> tuple[str, str, str]:
    raw = str(index or "sse").strip()
    key = MARKET_HISTORY_ALIASES.get(raw, MARKET_HISTORY_ALIASES.get(raw.lower(), raw.lower()))
    if key in MARKET_HISTORY_INDEXES:
        symbol, name = MARKET_HISTORY_INDEXES[key]
        return key, symbol, name
    code = raw.upper()
    for item_key, (symbol, name) in MARKET_HISTORY_INDEXES.items():
        if code in {symbol, symbol.split(".", 1)[0]}:
            return item_key, symbol, name
    symbol, name = MARKET_HISTORY_INDEXES["sse"]
    return "sse", symbol, name


def json_float(value: Any, digits: int = 2) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return round(out, digits)


def prepare_market_history_frame(df: Any, days: int) -> Any:
    import pandas as pd

    out = df.copy()
    for col in ("open", "high", "low", "close", "volume", "amount", "prev_close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "date" not in out.columns and "datetime" in out.columns:
        out["date"] = pd.to_datetime(out["datetime"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "pct_chg" not in out.columns:
        basis = out["prev_close"] if "prev_close" in out.columns else out["close"].shift(1)
        out["pct_chg"] = (out["close"] / basis - 1.0) * 100.0
    return _finalize_market_history_frame(out, days)


def _finalize_market_history_frame(df, days: int):
    import pandas as pd

    cols = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]
    for col in cols:
        if col not in df.columns:
            df[col] = None
    for col in ("open", "high", "low", "close", "volume", "amount", "pct_chg"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    out = df.dropna(subset=["date", "close"]).sort_values("date").tail(days)
    return out[cols].reset_index(drop=True)


def fetch_market_history_frame(symbol: str, days: int, tool_context: ToolContext | None) -> tuple[Any, str, list[str]]:
    errors: list[str] = []
    api_key = get_credential(tool_context, "tickflow_api_key", "TICKFLOW_API_KEY")
    if api_key:
        try:
            from integrations.tickflow_client import TickFlowClient

            client = TickFlowClient(api_key=api_key)
            return client.get_klines(symbol, period="1d", count=days, adjust="none"), "tickflow", errors
        except Exception as e:
            errors.append(f"tickflow: {e}")
    else:
        errors.append("tickflow: TICKFLOW_API_KEY 未配置")
    return _fetch_market_history_fallback(symbol, days, tool_context, errors)


def _fetch_market_history_fallback(
    symbol: str, days: int, tool_context: ToolContext | None, errors: list[str]
) -> tuple[Any, str, list[str]]:
    try:
        ensure_tushare_token(tool_context)
        from integrations.index_data_source import fetch_index_hist

        end = date.today()
        start = end - timedelta(days=int(days * 2.4) + 30)
        return fetch_index_hist(symbol, start, end), "tushare/akshare", errors
    except Exception as e:
        errors.append(f"tushare/akshare: {e}")
    raise RuntimeError("; ".join(errors))


def market_history_summary(df: Any) -> dict[str, Any]:
    close = df["close"]
    volume = df["volume"]
    latest = df.iloc[-1]
    tail20 = df.tail(min(len(df), 20))
    prior = df.iloc[:-20] if len(df) > 20 else df.iloc[:0]
    return {
        "latest_date": str(latest["date"]),
        "latest_close": json_float(latest["close"]),
        "latest_pct_chg": json_float(latest["pct_chg"]),
        "period_return_pct": json_float((float(close.iloc[-1]) / float(close.iloc[0]) - 1.0) * 100.0),
        "recent_20d_return_pct": json_float(
            (float(tail20["close"].iloc[-1]) / float(tail20["close"].iloc[0]) - 1.0) * 100.0
        ),
        "latest_volume_ratio_20d": json_float(float(latest["volume"]) / float(tail20["volume"].mean())),
        "recent_20d_volume_vs_prior": json_float(_recent_volume_ratio(tail20, prior)),
        "max_drawdown_pct": json_float(((close / close.cummax()) - 1.0).mul(100).min()),
        "up_days": int((df["pct_chg"] > 0).sum()),
        "down_days": int((df["pct_chg"] < 0).sum()),
        "price_up_volume_up_days": int(((df["pct_chg"] > 0) & (volume > volume.shift(1))).sum()),
        "price_down_volume_up_days": int(((df["pct_chg"] < 0) & (volume > volume.shift(1))).sum()),
    }


def _recent_volume_ratio(tail20, prior) -> float | None:
    prior_volume = prior["volume"].mean() if len(prior) else None
    return float(tail20["volume"].mean()) / float(prior_volume) if prior_volume else None


def market_history_rows(df: Any) -> list[dict[str, Any]]:
    return [
        {
            "date": str(row.get("date", "")),
            "open": json_float(row.get("open")),
            "high": json_float(row.get("high")),
            "low": json_float(row.get("low")),
            "close": json_float(row.get("close")),
            "pct_chg": json_float(row.get("pct_chg")),
            "volume": json_float(row.get("volume"), 0),
        }
        for row in df.to_dict("records")
    ]


def get_market_history(days: int = 100, index: str = "sse", tool_context: ToolContext | None = None) -> dict:
    try:
        requested_days = max(1, min(int(days or 100), 320))
        lookback = max(20, requested_days)
        key, symbol, name = resolve_market_history_index(index)
        raw, source, errors = fetch_market_history_frame(symbol, lookback, tool_context)
        df = prepare_market_history_frame(raw, lookback).tail(requested_days).reset_index(drop=True)
        if df.empty:
            return {"error": f"{name} {symbol} 没有可用历史 K 线", "source": source}
        return {
            "ok": True,
            "index": {"key": key, "symbol": symbol, "name": name},
            "requested_days": requested_days,
            "returned_days": int(len(df)),
            "source": source,
            "fallback_errors": errors,
            "summary": market_history_summary(df),
            "rows": market_history_rows(df),
        }
    except Exception as e:
        logger.exception("get_market_history error")
        return {"error": str(e)}
