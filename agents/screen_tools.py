"""Agent-facing Wyckoff funnel screen tool."""

from __future__ import annotations

import logging
from typing import Any

from agents.tool_context import ToolContext, ensure_tushare_token
from core.candidate_policy import candidate_score_value
from core.candidate_ranker import TRIGGER_SHORT_LABELS
from core.funnel_taxonomy import source_label

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
        trade_mode = _trade_mode_summary(details)
        top_candidates = _ranked_candidates(trigger_groups, symbols, details.get("name_map") or {}, details)
        return {
            "ok": bool(ok),
            "board": board,
            "summary": _screen_summary(metrics, symbols),
            "trade_mode": trade_mode,
            "action_plan": _action_plan(trade_mode, top_candidates),
            "top_candidates": top_candidates,
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


def _screen_summary(metrics: dict, symbols_for_report: list[Any]) -> dict:
    return {
        "total_scanned": int(metrics.get("total_symbols", 0)),
        "layer1_passed": int(metrics.get("layer1", 0)),
        "layer2_passed": int(metrics.get("layer2", 0)),
        "layer3_passed": int(metrics.get("layer3", 0)),
        "report_candidates": len(_report_rows(symbols_for_report)),
    }


def _trade_mode_summary(details: dict) -> dict:
    mode = details.get("trade_mode") if isinstance(details, dict) else {}
    if not isinstance(mode, dict):
        return {}
    fields = (
        "regime",
        "mode",
        "label",
        "action",
        "reason",
        "allow_ai_review",
        "allow_recommendation_write",
    )
    return {field: mode[field] for field in fields if field in mode}


def _action_plan(trade_mode: dict, top_candidates: list[dict]) -> dict:
    report_candidates = [row for row in top_candidates if row.get("selected_for_report")]
    watch_candidates = [row for row in top_candidates if not row.get("selected_for_report")]
    return {
        "primary_action": str(trade_mode.get("action") or _candidate_action_label(trade_mode)),
        "candidate_action": _candidate_action_label(trade_mode),
        "new_buy_allowed": bool(trade_mode.get("allow_recommendation_write")),
        "ai_review_allowed": bool(trade_mode.get("allow_ai_review")),
        "report_candidates": _candidate_refs(report_candidates),
        "watch_candidates": _candidate_refs(watch_candidates),
    }


def _candidate_action_label(trade_mode: dict) -> str:
    mode = str(trade_mode.get("mode") or "").strip()
    if mode == "observe_only":
        return "只观察，不新增买入"
    if mode == "repair_review":
        return "修复复核，暂不写正式推荐"
    if mode == "confirmation_only":
        return "等待二次确认后再行动"
    if mode == "risk_on":
        return "允许候选进入AI复核"
    return "先复核候选质量"


def _candidate_refs(candidates: list[dict], *, limit: int = 5) -> list[dict]:
    return [_candidate_ref(row) for row in candidates[:limit]]


def _candidate_ref(row: dict) -> dict:
    payload = {
        "code": row.get("code"),
        "name": row.get("name"),
        "profile": _candidate_profile(row),
        "rank_reason": row.get("rank_reason"),
        "priority_score": row.get("priority_score"),
        "selection_source": row.get("selection_source"),
        "track": row.get("track"),
        "stage": row.get("stage"),
        "tag": row.get("tag"),
        "triggers": row.get("triggers"),
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def _candidate_profile(row: dict) -> str:
    parts = [
        _track_label(row.get("track")),
        _stage_label(row.get("stage")),
        source_label(str(row.get("selection_source") or "")),
        _trigger_profile(row.get("triggers")),
    ]
    return " / ".join(dict.fromkeys(part for part in parts if part))


def _track_label(raw: object) -> str:
    return {"Trend": "趋势线", "Accum": "吸筹线"}.get(str(raw or "").strip(), "")


def _stage_label(raw: object) -> str:
    stage = str(raw or "").strip()
    return {"Markup": "主升阶段", "Accum_B": "吸筹B段", "Accum_C": "吸筹C段"}.get(stage, stage)


def _trigger_profile(raw: object) -> str:
    if not isinstance(raw, list):
        return ""
    labels = [TRIGGER_SHORT_LABELS.get(str(trigger), str(trigger)) for trigger in raw[:4] if str(trigger)]
    return f"触发:{'+'.join(labels)}" if labels else ""


def _ranked_candidates(
    trigger_groups: dict,
    symbols_for_report: list[Any],
    name_map: dict,
    details: dict | None = None,
    *,
    limit: int = 20,
) -> list[dict]:
    selected_rows = _report_rows(symbols_for_report)
    selected = set(selected_rows)
    priority_scores = _priority_score_map(details or {}, selected_rows)
    rows: dict[str, dict] = {}
    for trigger_name, candidates in trigger_groups.items():
        for candidate in candidates:
            code = str(candidate.get("code") or "").strip()
            if not code:
                continue
            row = rows.setdefault(
                code,
                _candidate_row(code, candidate.get("name") or name_map.get(code), selected_rows.get(code), selected),
            )
            row["score"] = max(float(row["score"]), candidate_score_value(candidate.get("score")))
            row["priority_score"] = max(float(row["priority_score"]), candidate_score_value(priority_scores.get(code)))
            if trigger_name not in row["triggers"]:
                row["triggers"].append(trigger_name)
    for code, report_row in selected_rows.items():
        row = rows.setdefault(code, _candidate_row(code, name_map.get(code), report_row, selected))
        row["priority_score"] = max(float(row["priority_score"]), candidate_score_value(priority_scores.get(code)))
    ranked = list(rows.values())
    ranked.sort(key=_candidate_sort_key)
    return [_final_candidate_row(row) for row in ranked[:limit]]


def _report_rows(symbols_for_report: list[Any]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for order, item in enumerate(symbols_for_report or [], start=1):
        code = _symbol_code(item)
        if not code:
            continue
        row = dict(item) if isinstance(item, dict) else {}
        row["_report_order"] = order
        rows.setdefault(code, row)
    return rows


def _symbol_code(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("code") or item.get("symbol") or "").strip()
    return str(item or "").strip()


def _priority_score_map(details: dict, selected_rows: dict[str, dict]) -> dict[str, float]:
    raw = details.get("priority_score_map") if isinstance(details, dict) else {}
    scores = {str(code): candidate_score_value(score) for code, score in (raw or {}).items()}
    for code, row in selected_rows.items():
        scores[code] = max(candidate_score_value(scores.get(code)), candidate_score_value(row.get("priority_score")))
    return scores


def _candidate_row(code: str, name: object, report_row: dict | None, selected: set[str]) -> dict:
    report_row = report_row or {}
    return {
        "code": code,
        "name": str(report_row.get("name") or name or code),
        "score": 0.0,
        "priority_score": candidate_score_value(report_row.get("priority_score")),
        "priority_rank": int(report_row.get("priority_rank") or report_row.get("_report_order") or 0),
        "triggers": [],
        "selected_for_report": code in selected,
        "selection_source": str(report_row.get("selection_source") or "").strip(),
        "track": str(report_row.get("track") or "").strip(),
        "stage": str(report_row.get("stage") or "").strip(),
        "tag": str(report_row.get("tag") or "").strip(),
    }


def _candidate_sort_key(row: dict) -> tuple:
    priority_rank = int(row.get("priority_rank") or 999999)
    return (
        not bool(row["selected_for_report"]),
        priority_rank,
        -candidate_score_value(row.get("priority_score")),
        -candidate_score_value(row.get("score")),
        row["code"],
    )


def _final_candidate_row(row: dict) -> dict:
    return {
        "code": row["code"],
        "name": row["name"],
        "score": round(candidate_score_value(row.get("score")), 2),
        "priority_score": round(candidate_score_value(row.get("priority_score")), 2),
        "priority_rank": int(row["priority_rank"]) if row.get("priority_rank") else None,
        "triggers": list(row["triggers"]),
        "selected_for_report": bool(row["selected_for_report"]),
        "selection_source": row["selection_source"],
        "track": row["track"],
        "stage": row["stage"],
        "tag": row["tag"],
        "rank_reason": _rank_reason(row),
    }


def _rank_reason(row: dict) -> str:
    parts: list[str] = []
    if row["selected_for_report"]:
        rank = int(row.get("priority_rank") or 0)
        parts.append(f"研报候选#{rank}" if rank else "研报候选")
    if candidate_score_value(row.get("priority_score")):
        parts.append(f"优先分 {candidate_score_value(row.get('priority_score')):.2f}")
    if row["triggers"]:
        labels = [TRIGGER_SHORT_LABELS.get(str(trigger), str(trigger)) for trigger in row["triggers"]]
        parts.append("+".join(labels))
    return "；".join(parts) or "触发候选"
