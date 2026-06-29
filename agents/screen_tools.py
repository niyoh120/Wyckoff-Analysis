"""Agent-facing Wyckoff funnel screen tool."""

from __future__ import annotations

import logging

from agents.tool_context import ToolContext, ensure_tushare_token
from core.candidate_policy import candidate_score_value

logger = logging.getLogger(__name__)

_VALID_BOARDS = {"all", "main", "chinext", "star"}
_BOARD_ALIAS = {
    "gem": "chinext",
    "创业板": "chinext",
    "主板": "main",
    "科创板": "star",
    "科创": "star",
    "star": "star",
    "全部": "all",
    "main_chinext": "all",
    "main-chinext": "all",
    "main+chinext": "all",
}


def screen_stocks(board: str = "all", tool_context: ToolContext | None = None) -> dict:
    """运行 Wyckoff 五层漏斗筛选。"""
    try:
        ensure_tushare_token(tool_context)
        board = _normalize_board(board)
        if board not in _VALID_BOARDS:
            return {"error": f"不支持的 board 值 '{board}'，可选: all / main / chinext / star"}
        ok, symbols, _bench_ctx, details = _run_funnel_with_board(board)
        metrics = details.get("metrics") or {}
        return {
            "ok": bool(ok),
            "summary": {
                "total_scanned": int(metrics.get("total_symbols", 0)),
                "layer1_passed": int(metrics.get("layer1", 0)),
                "layer2_passed": int(metrics.get("layer2", 0)),
                "layer3_passed": int(metrics.get("layer3", 0)),
            },
            "trigger_groups": _trigger_summary(details),
            "top_sectors": metrics.get("top_sectors", []),
            "symbols_for_report": symbols,
        }
    except Exception as e:
        logger.exception("screen_stocks error")
        return {"error": str(e)}


def _normalize_board(board: str) -> str:
    board = str(board or "all").strip().lower()
    return _BOARD_ALIAS.get(board, board)


def _run_funnel_with_board(board: str):
    from workflows.wyckoff_funnel import run as run_funnel

    return run_funnel("", notify=False, return_details=True, pool_board=board, executor_mode="thread")


def _trigger_summary(details: dict) -> dict:
    triggers = details.get("triggers") or {}
    name_map = details.get("name_map") or {}
    return {
        trigger_name: [
            {
                "code": str(code),
                "name": str(name_map.get(str(code), code)),
                "score": round(candidate_score_value(score), 2),
            }
            for code, score in rows
        ]
        for trigger_name, rows in triggers.items()
    }
