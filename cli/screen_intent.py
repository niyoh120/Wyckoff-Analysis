"""Shared helpers for stock-screen intent arguments."""

from __future__ import annotations

_BOARD_HINTS = (
    ("main_chinext_star", ("主板+创业板", "主板和创业板", "主创", "main_chinext", "main-chinext", "main+chinext")),
    ("chinext", ("创业板", "创板", "gem", "chinext")),
    ("star", ("科创板", "科创", "star")),
    ("bse", ("北交所", "北交", "bse")),
    ("main", ("沪深主板", "主板", "main")),
    ("all", ("全a", "全 a", "全市场", "全量", "全部", "所有", "all")),
)

_STYLE_HINTS = (
    ("trend", ("强势", "趋势", "右侧", "突破", "主升")),
    ("pullback", ("低吸", "吸筹", "左侧", "回踩", "埋伏")),
    ("quality", ("稳健", "高质量", "质量", "安全")),
)

_FULL_SCAN_HINTS = (
    "全量",
    "完整扫描",
    "完整筛选",
    "完整复核",
    "正式扫描",
    "正式筛选",
    "正式复核",
    "跑完整",
)

_FINANCIAL_METRICS_ON_HINTS = (
    "财务过滤",
    "财务指标",
    "财务数据",
    "基本面",
    "财报",
    "roe",
    "估值",
)

_FINANCIAL_METRICS_OFF_HINTS = (
    "快扫",
    "快速扫",
    "快速筛",
    "粗扫",
    "先扫",
    "先筛",
)


def stock_screen_suggested_args(text: str, *, include_default_board: bool = True) -> dict[str, str]:
    """Infer simple screen_stocks arguments from user wording."""

    payload: dict[str, str] = {}
    board = stock_screen_board_hint(text)
    if board or include_default_board:
        payload["board"] = board or "all"
    if style := stock_screen_style_hint(text):
        payload["style"] = style
    if limit := stock_screen_limit_hint(text):
        payload["limit"] = limit
    if financial_metrics := stock_screen_financial_metrics_hint(text):
        payload["financial_metrics"] = financial_metrics
    return payload


def stock_screen_board_hint(text: str) -> str:
    normalized = _normalize_text(text)
    for board, hints in _BOARD_HINTS:
        if any(hint in normalized for hint in hints):
            return board
    return ""


def stock_screen_style_hint(text: str) -> str:
    normalized = _normalize_text(text)
    styles = [style for style, hints in _STYLE_HINTS if any(hint in normalized for hint in hints)]
    return ",".join(dict.fromkeys(styles))


def stock_screen_limit_hint(text: str) -> str:
    normalized = _normalize_text(text)
    return "0" if any(hint in normalized for hint in _FULL_SCAN_HINTS) else ""


def stock_screen_financial_metrics_hint(text: str) -> str:
    normalized = _normalize_text(text)
    if any(hint in normalized for hint in _FINANCIAL_METRICS_ON_HINTS):
        return "true"
    if any(hint in normalized for hint in _FINANCIAL_METRICS_OFF_HINTS):
        return "false"
    return ""


def _normalize_text(text: str) -> str:
    return str(text or "").strip().lower()
