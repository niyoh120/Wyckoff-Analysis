"""Agent-facing market symbol search tools."""

from __future__ import annotations

import logging

from agents.tool_context import ToolContext

logger = logging.getLogger(__name__)


def search_stock_by_name(keyword: str, tool_context: ToolContext | None = None) -> list[dict]:
    """根据关键词搜索 A 股 / ETF / 美股 / 港股，支持名称和代码双向模糊搜索。"""
    try:
        from integrations.fetch_a_share_csv import get_all_stocks

        kw = keyword.strip()
        results = _search_a_share_stocks(get_all_stocks(), kw)
        _enrich_search_results(results[:3])
        if len(results) < 10:
            results.extend(_search_market_universe_meta(kw, 10 - len(results)))
        if not results:
            return [{"message": f"未找到与 '{kw}' 匹配的股票"}]
        return results
    except Exception as e:
        logger.exception("search_stock_by_name error")
        return [{"error": str(e)}]


def _search_a_share_stocks(stocks: list[dict], keyword: str) -> list[dict]:
    results: list[dict] = []
    for stock in stocks:
        code = stock.get("code", "")
        name = stock.get("name", "")
        if keyword in name or keyword in code:
            results.append({"code": code, "name": name})
            if len(results) >= 10:
                break
    return results


def _search_market_universe_meta(keyword: str, limit: int) -> list[dict]:
    try:
        from tools.market_universe_meta import search_market_meta

        rows = search_market_meta(keyword, limit=max(limit, 0))
    except Exception:
        return []
    return [
        {
            "code": str(row.get("code", "") or ""),
            "symbol": str(row.get("symbol", "") or ""),
            "name": str(row.get("name", "") or row.get("symbol", "") or row.get("code", "")),
            "market": str(row.get("market", "") or ""),
            "asset_type": str(row.get("asset_type", "") or ""),
            "currency": str(row.get("currency", "") or ""),
        }
        for row in rows
    ]


def _enrich_search_results(items: list[dict]) -> None:
    fetch_stock_spot_snapshot = _spot_snapshot_fetcher()
    cap_map = _market_cap_map()
    for item in items:
        code = item["code"]
        if fetch_stock_spot_snapshot:
            _attach_spot_snapshot(item, fetch_stock_spot_snapshot, code)
        if cap_map:
            item["market_cap_yi"] = cap_map.get(code)
        item["news"] = _fetch_news_with_timeout(code)


def _spot_snapshot_fetcher():
    try:
        from integrations.spot_snapshot import fetch_stock_spot_snapshot

        return fetch_stock_spot_snapshot
    except Exception:
        return None


def _market_cap_map() -> dict[str, float]:
    try:
        from integrations.market_metadata import fetch_market_cap_map

        return fetch_market_cap_map()
    except Exception:
        logger.debug("failed to fetch market cap map", exc_info=True)
        return {}


def _attach_spot_snapshot(item: dict, fetch_stock_spot_snapshot, code: str) -> None:
    try:
        snap = fetch_stock_spot_snapshot(code)
    except Exception:
        logger.debug("failed to fetch spot snapshot for %s", code, exc_info=True)
        return
    if snap:
        item["price"] = snap.get("close")
        item["pct_chg"] = snap.get("pct_chg")


def _fetch_news_with_timeout(code: str, timeout: float = 5.0) -> list[str]:
    import concurrent.futures

    def _fetch():
        from datetime import datetime, timedelta

        import akshare as ak
        import pandas as pd

        df = ak.stock_news_em(symbol=code)
        cutoff = datetime.now() - timedelta(days=7)
        df["发布时间"] = pd.to_datetime(df["发布时间"])
        recent = df[df["发布时间"] >= cutoff]
        return recent["新闻标题"].head(5).tolist()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_fetch)
            return future.result(timeout=timeout)
    except Exception:
        return []
