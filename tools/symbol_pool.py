"""
股票池解析工具。

根据环境变量选择股票来源（手动指定 / 板块筛选 / 全市场默认）。
"""

from __future__ import annotations

import os

from integrations.fetch_a_share_csv import (
    _normalize_symbols,
    get_stocks_by_board,
)
from tools.funnel_config import parse_int_env


def _stock_name_map() -> dict[str, str]:
    """获取全部 A 股 + ETF 代码→名称映射（如失败返回空 dict）。"""
    try:
        from integrations.fetch_a_share_csv import get_all_stocks

        items = get_all_stocks()
        result = {x.get("code", ""): x.get("name", "") for x in items if isinstance(x, dict)}
    except Exception:
        result = {}
    result.update(_etf_name_map())
    return result


def _etf_name_map() -> dict[str, str]:
    """从结构化 ETF meta 加载 ETF 名称映射。"""
    from contextlib import suppress
    from pathlib import Path

    with suppress(Exception):
        from integrations.data_source import load_symbol_name_map

        meta_map = load_symbol_name_map(("etf_cn",))
        out = {code: name for code, name in meta_map.items() if len(code) == 6 and code.isdigit()}
        if out:
            return out

    path = Path(__file__).resolve().parent.parent / "data" / "market_universes" / "etf_cn.txt"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 6 and parts[0].isdigit():
            out[parts[0]] = f"{parts[1]}ETF"
    return out


def _pool_stats(
    mode: str,
    *,
    main: int,
    chinext: int,
    star: int,
    merged: int,
    st_excluded: int,
    limit: int,
) -> dict[str, int | str]:
    return {
        "pool_mode": mode,
        "pool_main": main,
        "pool_chinext": chinext,
        "pool_star": star,
        "pool_merged": merged,
        "pool_st_excluded": st_excluded,
        "pool_limit": limit,
    }


def _merge_code_to_name(items: list[dict[str, str]]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for item in items:
        code = str(item.get("code", "")).strip()
        if code and code not in merged:
            merged[code] = str(item.get("name", "")).strip()
    return merged


def _symbols_from_map(
    code_to_name: dict[str, str],
    limit_count: int,
) -> tuple[list[str], dict[str, str], int]:
    merged_symbols = _normalize_symbols(list(code_to_name.keys()))
    symbols = merged_symbols[:limit_count] if limit_count > 0 else merged_symbols
    return symbols, {code: code_to_name.get(code, "") for code in symbols}, len(merged_symbols)


def _board_counts() -> tuple[int, int, int]:
    return (
        len(get_stocks_by_board("main")),
        len(get_stocks_by_board("chinext")),
        len(get_stocks_by_board("star")),
    )


def _resolve_board_pool(
    board_name: str,
    limit_count: int,
) -> tuple[list[str], dict[str, str], dict[str, int | str]]:
    effective_board = "all" if board_name in {"all", "main_chinext"} else board_name
    items = get_stocks_by_board(effective_board)
    symbols, name_map, merged = _symbols_from_map(_merge_code_to_name(items), limit_count)
    if effective_board == "all":
        main, chinext, star = _board_counts()
    else:
        main = len(items) if board_name == "main" else 0
        chinext = len(items) if board_name == "chinext" else 0
        star = len(items) if board_name == "star" else 0
    return (
        symbols,
        name_map,
        _pool_stats(
            "board",
            main=main,
            chinext=chinext,
            star=star,
            merged=merged,
            st_excluded=0,
            limit=limit_count,
        ),
    )


def _resolve_default_pool(limit_count: int) -> tuple[list[str], dict[str, str], dict[str, int | str]]:
    main_items = get_stocks_by_board("main")
    chinext_items = get_stocks_by_board("chinext")
    star_items = get_stocks_by_board("star")
    code_to_name = _merge_code_to_name(main_items + chinext_items + star_items)
    merged_symbols = _normalize_symbols(list(code_to_name.keys()))
    st_set = {sym for sym in merged_symbols if "ST" in code_to_name.get(sym, "").upper()}
    all_symbols = [sym for sym in merged_symbols if sym not in st_set]
    if limit_count > 0:
        all_symbols = all_symbols[:limit_count]
    stats = _pool_stats(
        "default",
        main=len(main_items),
        chinext=len(chinext_items),
        star=len(star_items),
        merged=len(merged_symbols),
        st_excluded=len(st_set),
        limit=limit_count,
    )
    return all_symbols, {code: code_to_name.get(code, "") for code in all_symbols}, stats


def resolve_symbol_pool_from_env() -> tuple[list[str], dict[str, str], dict[str, int | str]]:
    """
    根据环境变量 FUNNEL_POOL_MODE / FUNNEL_POOL_MANUAL_SYMBOLS 等
    解析当前使用的股票池。

    返回: (symbols, name_map, pool_stats)
    """
    pool_mode = str(os.getenv("FUNNEL_POOL_MODE", "") or "").strip().lower()
    limit_count = max(parse_int_env("FUNNEL_POOL_LIMIT_COUNT", 0), 0)

    if pool_mode == "manual":
        manual_raw = str(os.getenv("FUNNEL_POOL_MANUAL_SYMBOLS", "") or "")
        all_name_map = _stock_name_map()
        symbols = _normalize_symbols([x.strip() for x in manual_raw.replace(";", ",").replace("\n", ",").split(",")])
        name_map = {code: all_name_map.get(code, "") for code in symbols}
        return (
            symbols,
            name_map,
            _pool_stats("manual", main=0, chinext=0, star=0, merged=len(symbols), st_excluded=0, limit=limit_count),
        )

    board_name = str(os.getenv("FUNNEL_POOL_BOARD", "") or "").strip().lower()
    if pool_mode == "board" and board_name in {"main", "chinext", "star", "all", "main_chinext"}:
        return _resolve_board_pool(board_name, limit_count)

    return _resolve_default_pool(limit_count)
