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


def stock_screen_suggested_args(text: str, *, include_default_board: bool = True) -> dict[str, str]:
    """Infer simple screen_stocks arguments from user wording."""

    payload: dict[str, str] = {}
    board = stock_screen_board_hint(text)
    if board or include_default_board:
        payload["board"] = board or "all"
    if style := stock_screen_style_hint(text):
        payload["style"] = style
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


def _normalize_text(text: str) -> str:
    return str(text or "").strip().lower()
