"""A-share board classification helpers."""

from __future__ import annotations

MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
CHINEXT_PREFIXES = ("300", "301")
STAR_PREFIXES = ("688", "689")
BSE_PREFIXES = ("43", "83", "87", "88", "92")


def cn_board(code: object) -> str:
    text = str(code or "").strip()
    if text.startswith(MAIN_BOARD_PREFIXES):
        return "main"
    if text.startswith(CHINEXT_PREFIXES):
        return "chinext"
    if text.startswith(STAR_PREFIXES):
        return "star"
    if text.startswith(BSE_PREFIXES):
        return "bse"
    return "unknown"


def is_supported_cn_board(code: object, *, include_bse: bool = True) -> bool:
    board = cn_board(code)
    if board == "bse" and not include_bse:
        return False
    return board in {"main", "chinext", "star", "bse"}


def is_main_or_chinext(code: object) -> bool:
    return cn_board(code) in {"main", "chinext"}


def is_star_or_bse(code: object) -> bool:
    return cn_board(code) in {"star", "bse"}
