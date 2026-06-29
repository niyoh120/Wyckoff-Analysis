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
        trigger_groups = _trigger_summary(details)
        return {
            "ok": bool(ok),
            "board": board,
            "summary": {
                "total_scanned": int(metrics.get("total_symbols", 0)),
                "layer1_passed": int(metrics.get("layer1", 0)),
                "layer2_passed": int(metrics.get("layer2", 0)),
                "layer3_passed": int(metrics.get("layer3", 0)),
            },
            "top_candidates": _ranked_candidates(trigger_groups, symbols, details.get("name_map") or {}),
            "trigger_groups": trigger_groups,
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


def _ranked_candidates(
    trigger_groups: dict,
    symbols_for_report: list[str],
    name_map: dict,
    *,
    limit: int = 20,
) -> list[dict]:
    selected = {str(code) for code in symbols_for_report}
    rows: dict[str, dict] = {}
    for trigger_name, candidates in trigger_groups.items():
        for candidate in candidates:
            code = str(candidate.get("code") or "").strip()
            if not code:
                continue
            row = rows.setdefault(code, _candidate_row(code, candidate.get("name") or name_map.get(code), selected))
            row["score"] = max(float(row["score"]), candidate_score_value(candidate.get("score")))
            if trigger_name not in row["triggers"]:
                row["triggers"].append(trigger_name)
    for code in selected:
        rows.setdefault(code, _candidate_row(code, name_map.get(code), selected))
    ranked = list(rows.values())
    ranked.sort(key=lambda row: (-float(row["score"]), not row["selected_for_report"], row["code"]))
    return [_final_candidate_row(row) for row in ranked[:limit]]


def _candidate_row(code: str, name: object, selected: set[str]) -> dict:
    return {
        "code": code,
        "name": str(name or code),
        "score": 0.0,
        "triggers": [],
        "selected_for_report": code in selected,
    }


def _final_candidate_row(row: dict) -> dict:
    return {
        "code": row["code"],
        "name": row["name"],
        "score": round(candidate_score_value(row.get("score")), 2),
        "triggers": list(row["triggers"]),
        "selected_for_report": bool(row["selected_for_report"]),
    }
