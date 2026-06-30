"""Agent-facing Wyckoff funnel screen tool."""

from __future__ import annotations

import logging
from typing import Any

from agents.tool_context import ToolContext, ensure_tushare_token
from core.candidate_metadata import build_candidate_metadata_map, code6
from core.candidate_policy import candidate_score_value
from core.candidate_ranker import TRIGGER_SHORT_LABELS
from core.candidate_tracks import candidate_entry_track
from core.funnel_taxonomy import lane_label, source_label

logger = logging.getLogger(__name__)

_VALID_BOARDS = {"all", "main", "chinext", "star", "bse", "main_chinext_star"}
_BOARD_ALIAS = {
    "gem": "chinext",
    "创业板": "chinext",
    "主板": "main",
    "科创板": "star",
    "科创": "star",
    "北交所": "bse",
    "北交": "bse",
    "star": "star",
    "bse": "bse",
    "全部": "all",
    "main_chinext": "main_chinext_star",
    "main-chinext": "main_chinext_star",
    "main+chinext": "main_chinext_star",
}


def screen_stocks(board: str = "all", tool_context: ToolContext | None = None) -> dict:
    """运行 Wyckoff 五层漏斗筛选。"""
    try:
        ensure_tushare_token(tool_context)
        board = _normalize_board(board)
        if board not in _VALID_BOARDS:
            return {"error": f"不支持的 board 值 '{board}'，可选: all / main / chinext / star / bse"}
        ok, symbols, _bench_ctx, details = _run_funnel_with_board(board)
        metrics = details.get("metrics") or {}
        trigger_groups = _trigger_summary(details)
        trade_mode = _trade_mode_summary(details)
        top_candidates = _ranked_candidates(trigger_groups, symbols, details.get("name_map") or {}, details)
        result = {
            "ok": bool(ok),
            "board": board,
            "summary": _screen_summary(metrics, symbols),
            "trade_mode": trade_mode,
            "decision_brief": _decision_brief(trade_mode, top_candidates),
            "selection_brief": _selection_brief(trade_mode, top_candidates),
            "action_plan": _action_plan(trade_mode, top_candidates),
            "top_candidates": top_candidates,
            "trigger_groups": trigger_groups,
            "top_sectors": metrics.get("top_sectors", []),
            "symbols_for_report": symbols,
        }
        remember_screen_handoff(tool_context, result)
        return result
    except Exception as e:
        logger.exception("screen_stocks error")
        return {"error": str(e)}


def _normalize_board(board: str) -> str:
    board = str(board or "all").strip().lower()
    return _BOARD_ALIAS.get(board, board)


def remember_screen_handoff(tool_context: ToolContext | None, result: dict[str, Any]) -> None:
    if tool_context is None:
        return
    tool_context.state["last_screen_result"] = {
        "ok": result.get("ok"),
        "board": result.get("board"),
        "summary": result.get("summary", {}),
        "trade_mode": result.get("trade_mode", {}),
        "decision_brief": result.get("decision_brief", {}),
        "selection_brief": result.get("selection_brief", {}),
        "action_plan": result.get("action_plan", {}),
        "top_candidates": list(result.get("top_candidates") or [])[:20],
        "symbols_for_report": list(result.get("symbols_for_report") or [])[:10],
    }


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
        "review_targets": _review_targets(report_candidates, trade_mode),
        "report_candidates": _candidate_refs(report_candidates, trade_mode, "report"),
        "watch_candidates": _candidate_refs(watch_candidates, trade_mode, "watch"),
    }


def _decision_brief(trade_mode: dict, top_candidates: list[dict]) -> dict:
    report_candidates = [row for row in top_candidates if row.get("selected_for_report")]
    watch_candidates = [row for row in top_candidates if not row.get("selected_for_report")]
    return {
        "market_gate": _market_gate_line(trade_mode),
        "next_action": _candidate_action_label(trade_mode),
        "report_focus": _candidate_brief_items(report_candidates, trade_mode, "report"),
        "watch_focus": _candidate_brief_items(watch_candidates, trade_mode, "watch"),
    }


def _selection_brief(trade_mode: dict, top_candidates: list[dict]) -> dict:
    report_candidates = [row for row in top_candidates if row.get("selected_for_report")]
    candidates = report_candidates or top_candidates[:3]
    status = _selection_status(report_candidates, candidates, trade_mode)
    best_candidates = _selection_candidate_items(candidates, trade_mode, "report" if report_candidates else "watch")
    payload = {
        "status": status,
        "headline": _selection_headline(status, best_candidates),
        "best_codes": [row["code"] for row in best_candidates],
        "primary_pick": best_candidates[0] if best_candidates else {},
        "best_candidates": best_candidates,
        "tool_handoff": _selection_tool_handoff(status, best_candidates),
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _selection_status(report_candidates: list[dict], candidates: list[dict], trade_mode: dict) -> str:
    if not candidates:
        return "empty"
    if report_candidates and bool(trade_mode.get("allow_ai_review")):
        return "ready_for_ai_review"
    if report_candidates:
        return "blocked_by_market_gate"
    return "watch_only"


def _selection_candidate_items(candidates: list[dict], trade_mode: dict, bucket: str, *, limit: int = 5) -> list[dict]:
    return [_selection_candidate_item(row, trade_mode, bucket) for row in candidates[:limit]]


def _selection_candidate_item(row: dict, trade_mode: dict, bucket: str) -> dict:
    profile = _candidate_profile(row)
    rank_reason = str(row.get("rank_reason") or "").strip()
    why = "；".join(part for part in (profile, rank_reason) if part) or "候选证据不足"
    next_step = _candidate_next_step(trade_mode, bucket)
    return _drop_empty_candidate_fields(
        {
            "code": str(row.get("code") or "").strip(),
            "name": str(row.get("name") or row.get("code") or "").strip(),
            "tier": _candidate_quality_label(row),
            "why": why,
            "quality_factors": _candidate_quality_factors(row, next_step=next_step),
            "risk_factors": _candidate_risk_factors(row, trade_mode, bucket),
            "action_status": _candidate_action_status(trade_mode, bucket),
            "next_step": next_step,
            "priority_score": row.get("priority_score"),
            "score": row.get("score"),
            "track": row.get("track"),
            "stage": row.get("stage"),
            "candidate_lane": row.get("candidate_lane"),
            "entry_type": row.get("entry_type"),
        }
    )


def _selection_headline(status: str, best_candidates: list[dict]) -> str:
    if not best_candidates:
        return "本轮没有形成可复核候选"
    first = best_candidates[0]
    prefix = {
        "ready_for_ai_review": "本轮首选可进入 AI 研报复核",
        "blocked_by_market_gate": "本轮有强候选，但市场闸门未打开",
        "watch_only": "本轮只有观察候选",
    }.get(status, "本轮候选摘要")
    return f"{prefix}: {first.get('code')} {first.get('name')}"


def _selection_tool_handoff(status: str, best_candidates: list[dict]) -> dict:
    if status != "ready_for_ai_review":
        return {}
    codes = [str(row.get("code") or "").strip() for row in best_candidates if str(row.get("code") or "").strip()]
    return {
        "tool": "generate_ai_report",
        "args": {"stock_codes": codes[:10]},
        "reason": "首选候选已通过市场闸门，可进入 AI 研报复核",
    }


def _drop_empty_candidate_fields(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _review_targets(report_candidates: list[dict], trade_mode: dict) -> dict:
    codes = [str(row.get("code") or "").strip() for row in report_candidates if str(row.get("code") or "").strip()]
    payload = {
        "codes": codes[:10],
        "status": _review_target_status(codes, trade_mode),
        "reason": _review_target_reason(codes, trade_mode),
    }
    if payload["status"] == "ready":
        payload["tool"] = "generate_ai_report"
        payload["args"] = {"stock_codes": payload["codes"]}
    return payload


def _review_target_status(codes: list[str], trade_mode: dict) -> str:
    if not codes:
        return "empty"
    return "ready" if bool(trade_mode.get("allow_ai_review")) else "blocked"


def _review_target_reason(codes: list[str], trade_mode: dict) -> str:
    if not codes:
        return "本轮没有研报候选"
    if bool(trade_mode.get("allow_ai_review")):
        return "候选已可进入 AI 研报复核"
    return str(trade_mode.get("reason") or "市场风险闸门未打开，暂不进入 AI 研报复核")


def _market_gate_line(trade_mode: dict) -> str:
    label = str(trade_mode.get("label") or trade_mode.get("regime") or "").strip()
    action = str(trade_mode.get("action") or _candidate_action_label(trade_mode)).strip()
    reason = str(trade_mode.get("reason") or "").strip()
    parts = [part for part in (label, action, reason) if part]
    return " / ".join(parts) or "市场闸门未提供"


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


def _candidate_refs(candidates: list[dict], trade_mode: dict, bucket: str, *, limit: int = 5) -> list[dict]:
    return [_candidate_ref(row, trade_mode, bucket) for row in candidates[:limit]]


def _candidate_brief_items(candidates: list[dict], trade_mode: dict, bucket: str, *, limit: int = 5) -> list[dict]:
    return [_candidate_brief_item(row, trade_mode, bucket) for row in candidates[:limit]]


def _candidate_brief_item(row: dict, trade_mode: dict, bucket: str) -> dict:
    profile = _candidate_profile(row)
    rank_reason = str(row.get("rank_reason") or "").strip()
    next_step = _candidate_next_step(trade_mode, bucket)
    evidence = "；".join(part for part in (profile, rank_reason) if part) or "候选证据不足"
    code = str(row.get("code") or "").strip()
    name = str(row.get("name") or code).strip()
    return {
        "code": code,
        "name": name,
        "quality": _candidate_quality_label(row),
        "evidence": evidence,
        "quality_factors": _candidate_quality_factors(row, next_step=next_step),
        "risk_factors": _candidate_risk_factors(row, trade_mode, bucket),
        "action_status": _candidate_action_status(trade_mode, bucket),
        "next_step": next_step,
        "summary": f"{code} {name}: {evidence}；{next_step}",
    }


def _candidate_ref(row: dict, trade_mode: dict, bucket: str) -> dict:
    next_step = _candidate_next_step(trade_mode, bucket)
    payload = {
        "code": row.get("code"),
        "name": row.get("name"),
        "quality": _candidate_quality_label(row),
        "profile": _candidate_profile(row),
        "next_step": next_step,
        "rank_reason": row.get("rank_reason"),
        "quality_factors": _candidate_quality_factors(row, next_step=next_step),
        "risk_factors": _candidate_risk_factors(row, trade_mode, bucket),
        "action_status": _candidate_action_status(trade_mode, bucket),
        "priority_score": row.get("priority_score"),
        "selection_source": row.get("selection_source"),
        "track": row.get("track"),
        "stage": row.get("stage"),
        "tag": row.get("tag"),
        "candidate_lane": row.get("candidate_lane"),
        "entry_type": row.get("entry_type"),
        "triggers": row.get("triggers"),
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def _candidate_quality_label(row: dict) -> str:
    priority = candidate_score_value(row.get("priority_score"))
    score = candidate_score_value(row.get("score"))
    trigger_count = len(row.get("triggers") or [])
    if row.get("selected_for_report") and priority >= 10:
        return "高优先级研报候选"
    if row.get("selected_for_report"):
        return "研报候选"
    if score >= 8 or trigger_count >= 2:
        return "强观察候选"
    return "观察候选"


def _candidate_next_step(trade_mode: dict, bucket: str) -> str:
    if bucket == "watch":
        return "观察池跟踪，暂不进入本轮AI复核"
    mode = str(trade_mode.get("mode") or "").strip()
    if not bool(trade_mode.get("allow_ai_review")):
        return "只观察，等待市场风险闸门重新打开"
    if not bool(trade_mode.get("allow_recommendation_write")):
        return "可送AI做修复复核，但不写正式推荐"
    if mode == "confirmation_only":
        return "进入AI复核，等待二次确认后再行动"
    if mode == "risk_on":
        return "进入AI复核，合格后纳入新买候选"
    return "进入AI复核，先确认候选质量"


def _candidate_action_status(trade_mode: dict, bucket: str) -> str:
    if bucket == "watch":
        return "watch_only"
    mode = str(trade_mode.get("mode") or "").strip()
    if not bool(trade_mode.get("allow_ai_review")):
        return "blocked_by_market_gate"
    if not bool(trade_mode.get("allow_recommendation_write")):
        return "repair_review_only"
    if mode == "confirmation_only":
        return "confirmation_required"
    return "ready_for_ai_review"


def _candidate_profile(row: dict) -> str:
    parts = [
        _track_label(row.get("track")),
        _stage_label(row.get("stage")),
        _lane_profile(row),
        source_label(str(row.get("selection_source") or "")),
        _trigger_profile(row.get("triggers")),
    ]
    return " / ".join(dict.fromkeys(part for part in parts if part))


def _candidate_quality_factors(row: dict, *, next_step: str = "") -> list[str]:
    factors = [_candidate_quality_label(row)]
    factors.extend(_split_factor_text(_candidate_profile(row), " / "))
    factors.extend(_split_factor_text(str(row.get("rank_reason") or ""), "；"))
    if next_step:
        factors.append(next_step)
    return list(dict.fromkeys(factor for factor in factors if factor))


def _candidate_risk_factors(row: dict, trade_mode: dict | None = None, bucket: str = "") -> list[str]:
    factors: list[str] = []
    if bucket == "watch" or not bool(row.get("selected_for_report")):
        factors.append("未进入本轮研报候选")
    if not row.get("triggers") and not row.get("selected_for_report"):
        factors.append("触发信号未列明")
    if trade_mode:
        factors.extend(_trade_mode_risk_factors(trade_mode, bucket))
    return list(dict.fromkeys(factor for factor in factors if factor))


def _trade_mode_risk_factors(trade_mode: dict, bucket: str) -> list[str]:
    if bucket == "watch":
        return ["观察池，不进入本轮AI复核"]
    if not bool(trade_mode.get("allow_ai_review")):
        return [str(trade_mode.get("reason") or "市场风险闸门未打开")]
    if not bool(trade_mode.get("allow_recommendation_write")):
        return ["只做修复复核，不写正式推荐"]
    if str(trade_mode.get("mode") or "").strip() == "confirmation_only":
        return ["等待二次确认后再行动"]
    return []


def _split_factor_text(text: str, sep: str) -> list[str]:
    return [part.strip() for part in str(text or "").split(sep) if part.strip()]


def _lane_profile(row: dict) -> str:
    return lane_label(str(row.get("candidate_lane") or row.get("entry_type") or "").strip())


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
    metadata_map = _candidate_metadata_map(details or {})
    rows: dict[str, dict] = {}
    for trigger_name, candidates in trigger_groups.items():
        for candidate in candidates:
            code = str(candidate.get("code") or "").strip()
            if not code:
                continue
            row = rows.setdefault(
                code,
                _candidate_row(
                    code,
                    candidate.get("name") or name_map.get(code),
                    selected_rows.get(code),
                    selected,
                    _metadata_for_code(metadata_map, code),
                ),
            )
            row["score"] = max(float(row["score"]), candidate_score_value(candidate.get("score")))
            row["priority_score"] = max(float(row["priority_score"]), candidate_score_value(priority_scores.get(code)))
            if trigger_name not in row["triggers"]:
                row["triggers"].append(trigger_name)
    for code, report_row in selected_rows.items():
        row = rows.setdefault(
            code, _candidate_row(code, name_map.get(code), report_row, selected, _metadata_for_code(metadata_map, code))
        )
        row["priority_score"] = max(float(row["priority_score"]), candidate_score_value(priority_scores.get(code)))
    ranked = list(rows.values())
    ranked.sort(key=_candidate_sort_key)
    return [_final_candidate_row(row) for row in ranked[:limit]]


def _candidate_metadata_map(details: dict) -> dict[str, dict[str, Any]]:
    return build_candidate_metadata_map(
        _safe_dict_list(details.get("candidate_entries")),
        _safe_dict_list(details.get("mainline_candidates")),
    )


def _safe_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _metadata_for_code(metadata_map: dict[str, dict[str, Any]], code: str) -> dict[str, Any]:
    return metadata_map.get(code6(code)) or metadata_map.get(str(code or "").strip()) or {}


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


def _candidate_row(
    code: str,
    name: object,
    report_row: dict | None,
    selected: set[str],
    metadata: dict[str, Any] | None = None,
) -> dict:
    report_row = report_row or {}
    metadata = metadata or {}
    return {
        "code": code,
        "name": str(report_row.get("name") or name or code),
        "score": 0.0,
        "priority_score": candidate_score_value(report_row.get("priority_score")),
        "priority_rank": int(report_row.get("priority_rank") or report_row.get("_report_order") or 0),
        "triggers": [],
        "selected_for_report": code in selected,
        "selection_source": str(report_row.get("selection_source") or _metadata_selection_source(metadata)).strip(),
        "track": str(report_row.get("track") or _metadata_track(metadata)).strip(),
        "stage": str(report_row.get("stage") or metadata.get("candidate_status") or "").strip(),
        "tag": str(report_row.get("tag") or _metadata_tag(metadata)).strip(),
        "candidate_lane": str(report_row.get("candidate_lane") or metadata.get("candidate_lane") or "").strip(),
        "entry_type": str(report_row.get("entry_type") or metadata.get("entry_type") or "").strip(),
    }


def _metadata_selection_source(metadata: dict[str, Any]) -> str:
    lane = str(metadata.get("candidate_lane") or "").strip()
    if lane == "mainline":
        return "mainline"
    return "alpha_candidate" if metadata else ""


def _metadata_track(metadata: dict[str, Any]) -> str:
    if not any(metadata.get(field) for field in ("candidate_lane", "signal_key", "entry_type")):
        return ""
    return candidate_entry_track(metadata, default="", fields=("candidate_lane", "signal_key", "entry_type"))


def _metadata_tag(metadata: dict[str, Any]) -> str:
    return str(metadata.get("entry_type") or metadata.get("signal_key") or metadata.get("candidate_lane") or "").strip()


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
    rank_reason = _rank_reason(row)
    payload = {
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
        "candidate_lane": row["candidate_lane"],
        "entry_type": row["entry_type"],
        "rank_reason": rank_reason,
    }
    payload["quality_factors"] = _candidate_quality_factors(payload)
    payload["risk_factors"] = _candidate_risk_factors(payload)
    return payload


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
