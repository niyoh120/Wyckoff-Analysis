"""Shared tool-result serialization and compact previews."""

from __future__ import annotations

import json
import math
from typing import Any

PREVIEW_CHARS = 2_000


def serialize_tool_result(result: Any) -> str:
    """Serialize a tool result exactly once for message context."""

    return json.dumps(_json_safe(result), ensure_ascii=False, default=str, allow_nan=False)


def tool_result_preview(tool_name: str, result: Any, content: str = "") -> str:
    if isinstance(result, dict) and _is_recommendation_event_eval_result(tool_name, result):
        preview = _recommendation_event_eval_preview(result)
        if preview:
            return preview[:PREVIEW_CHARS]
    if tool_name == "screen_stocks" and isinstance(result, dict):
        preview = _screen_stocks_preview(result)
        if preview:
            return preview[:PREVIEW_CHARS]
    if tool_name == "generate_ai_report" and isinstance(result, dict):
        preview = _ai_report_preview(result)
        if preview:
            return preview[:PREVIEW_CHARS]
    if tool_name == "generate_strategy_decision" and isinstance(result, dict):
        preview = _strategy_decision_preview(result)
        if preview:
            return preview[:PREVIEW_CHARS]
    return content[:PREVIEW_CHARS]


def tool_result_brief_lines(tool_name: str, result: Any, *, max_lines: int = 3) -> list[str]:
    if not isinstance(result, dict) or result.get("error"):
        return []
    if _is_recommendation_event_eval_result(tool_name, result):
        return _recommendation_event_eval_brief_lines(result, max_lines=max_lines)
    if tool_name == "screen_stocks":
        return _screen_stocks_brief_lines(result, max_lines=max_lines)
    if tool_name == "generate_ai_report":
        return _ai_report_brief_lines(result, max_lines=max_lines)
    if tool_name == "generate_strategy_decision":
        return _strategy_decision_brief_lines(result, max_lines=max_lines)
    return []


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            return str(value)
    return value


def _is_recommendation_event_eval_result(tool_name: str, result: dict[str, Any]) -> bool:
    return (
        tool_name in {"recommendation_event_eval", "evaluate_recommendation_events"}
        or result.get("job_kind") == "recommendation_event_eval"
    )


def _recommendation_event_eval_preview(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    payload = _drop_empty_preview_fields(
        {
            "ok": result.get("ok"),
            "job_kind": result.get("job_kind"),
            "result_summary": _text_excerpt(result.get("result_summary"), 900),
            "metadata": _recommendation_metadata_preview(result.get("metadata")),
            "all": _recommendation_metric_preview(summary.get("all")),
            "ranking_decision": _recommendation_ranking_decision_preview(summary.get("ranking_decision")),
            "policy_selection": _recommendation_policy_selection_preview(result.get("policy_selection")),
        }
    )
    return serialize_tool_result(payload) if payload else ""


def _recommendation_event_eval_brief_lines(result: dict[str, Any], *, max_lines: int) -> list[str]:
    lines = [line.strip() for line in str(result.get("result_summary") or "").splitlines() if line.strip()]
    if not lines:
        lines = _recommendation_fallback_brief_lines(result)
    pick_lines = _recommendation_policy_brief_lines(result.get("policy_selection"))
    if pick_lines:
        keep = max(max_lines - len(pick_lines[:1]), 0)
        lines = lines[:keep] + pick_lines[: max_lines - keep]
    return lines[:max_lines]


def _recommendation_fallback_brief_lines(result: dict[str, Any]) -> list[str]:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    all_rows = summary.get("all") if isinstance(summary.get("all"), dict) else {}
    decision = summary.get("ranking_decision") if isinstance(summary.get("ranking_decision"), dict) else {}
    ready = f"{all_rows.get('rows_ready', 0)}/{all_rows.get('rows_total', 0)}"
    lines = [
        f"推荐事件评估: ready={ready}, hit={_format_pct(all_rows.get('hit_rate_pct'))}%, "
        f"ranking_decision={decision.get('status', 'unknown')}",
        _recommendation_decision_line(decision),
    ]
    if pick_line := _recommendation_policy_line(result.get("policy_selection")):
        lines.append(pick_line)
    return [line for line in lines if line]


def _recommendation_metadata_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = ("market", "horizon_days", "target_pct", "max_dates", "records", "codes")
    return _drop_empty_preview_fields({key: value.get(key) for key in keys})


def _recommendation_metric_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "rows_ready",
        "rows_total",
        "hit_rate_pct",
        "close_win_rate_pct",
        "avg_close_return_horizon_pct",
        "avg_mfe_horizon_pct",
        "avg_mae_horizon_pct",
    )
    return _drop_empty_preview_fields({key: value.get(key) for key in keys})


def _recommendation_ranking_decision_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "status": value.get("status"),
            "recommended_strategy": value.get("recommended_strategy"),
            "recommended_top_k": value.get("recommended_top_k"),
            "watch_strategy": value.get("watch_strategy"),
            "reason": value.get("reason"),
            "candidates": _recommendation_decision_candidates_preview(value.get("candidates")),
        }
    )


def _recommendation_decision_candidates_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(strategy): _drop_empty_preview_fields(
            {
                "status": row.get("status"),
                "top_k": row.get("top_k"),
                "decision_score": row.get("decision_score"),
                "rows_ready": row.get("rows_ready"),
                "hit_rate_delta_pct": row.get("hit_rate_delta_pct"),
                "avg_mfe_delta_pct": row.get("avg_mfe_delta_pct"),
                "avg_mae_delta_pct": row.get("avg_mae_delta_pct"),
                "sample_ok": row.get("sample_ok"),
                "lift_ok": row.get("lift_ok"),
                "risk_ok": row.get("risk_ok"),
            }
        )
        for strategy, row in value.items()
        if isinstance(row, dict)
    }


def _recommendation_policy_selection_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "status": value.get("status"),
            "selection_strategy": value.get("selection_strategy"),
            "top_k": value.get("top_k"),
            "recommend_date": value.get("recommend_date"),
            "uses_promoted_ranking": value.get("uses_promoted_ranking"),
            "watch_strategy": value.get("watch_strategy"),
            "reason": value.get("reason"),
            "action_plan": _recommendation_action_plan_preview(value.get("action_plan")),
            "picks": _recommendation_pick_preview_list(value.get("picks"), 6),
        }
    )


def _recommendation_action_plan_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "primary_action": value.get("primary_action"),
            "candidate_action": value.get("candidate_action"),
            "new_buy_allowed": value.get("new_buy_allowed"),
            "ai_review_allowed": value.get("ai_review_allowed"),
            "trade_readiness": value.get("trade_readiness"),
            "review_status": value.get("review_status"),
            "reason": value.get("reason"),
            "next_step": value.get("next_step"),
            "next_tool": value.get("next_tool"),
        }
    )


def _recommendation_pick_preview_list(value: Any, limit: int) -> list[dict[str, Any]]:
    rows = _preview_list(value, limit)
    return [_recommendation_pick_preview(row) for row in rows if isinstance(row, dict)]


def _recommendation_pick_preview(value: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "rank",
        "selection_strategy",
        "code",
        "name",
        "recommend_date",
        "is_ai_recommended",
        "funnel_score",
        "recommend_count",
        "candidate_shadow_score",
        "candidate_shadow_grade",
        "entry_quality_score",
        "entry_quality_grade",
        "entry_quality_risk_flags",
        "label_ready",
        "label_status",
        "action_status",
        "quality_factors",
        "risk_factors",
        "next_step",
    )
    return _drop_empty_preview_fields({key: value.get(key) for key in keys})


def _recommendation_decision_line(decision: dict[str, Any]) -> str:
    status = str(decision.get("status") or "unknown")
    strategy = str(decision.get("recommended_strategy") or decision.get("watch_strategy") or "score_only")
    top_k = decision.get("recommended_top_k") or "n/a"
    if status == "candidate":
        return f"排序接入候选: {strategy} top{top_k} 已通过样本/lift/风险门槛"
    if status == "watch":
        return f"排序观察项: {strategy} 有改善但未全部过门槛"
    return "排序策略: 继续保持 score_only"


def _recommendation_policy_line(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    picks = value.get("picks") if isinstance(value.get("picks"), list) else []
    names = [_candidate_name(pick) for pick in picks if isinstance(pick, dict)]
    names = [name for name in names if name]
    if not names:
        return ""
    strategy = str(value.get("selection_strategy") or "score_only")
    rec_date = value.get("recommend_date") or "-"
    return f"最新候选({rec_date}, {strategy}): {', '.join(names[:5])}"


def _recommendation_policy_brief_lines(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    picks = value.get("picks") if isinstance(value.get("picks"), list) else []
    lines = [_candidate_brief_line(pick) for pick in picks if isinstance(pick, dict)]
    return [line for line in lines if line]


def _format_pct(raw: Any) -> str:
    try:
        return f"{float(raw):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "n/a"


def _strategy_decision_preview(result: dict[str, Any]) -> str:
    payload = _drop_empty_preview_fields(
        {
            "ok": result.get("ok"),
            "status": result.get("status"),
            "reason": result.get("reason"),
            "report_source": result.get("report_source"),
            "candidate_count": result.get("candidate_count"),
            "reviewed_codes": _preview_list(result.get("reviewed_codes"), 12),
            "reviewed_symbols": _candidate_preview_list(result.get("reviewed_symbols"), 12),
            "candidate_guard_summary": _candidate_guard_preview(result.get("candidate_guard_summary")),
            "screen_summary": result.get("screen_summary"),
            "decision_brief": _screen_decision_preview(result.get("decision_brief")),
            "next_action": result.get("next_action"),
            "message": result.get("message"),
            "report_preview": _text_excerpt(result.get("report_preview"), 1000),
        }
    )
    return serialize_tool_result(payload) if payload else ""


def _ai_report_preview(result: dict[str, Any]) -> str:
    payload = _drop_empty_preview_fields(
        {
            "ok": result.get("ok"),
            "reason": result.get("reason"),
            "model": result.get("model"),
            "stock_count": result.get("stock_count"),
            "reviewed_codes": _preview_list(result.get("reviewed_codes"), 12),
            "reviewed_symbols": _candidate_preview_list(result.get("reviewed_symbols"), 12),
            "candidate_guard_summary": _candidate_guard_preview(result.get("candidate_guard_summary")),
            "next_action": result.get("next_action"),
            "next_tool": result.get("next_tool"),
            "report_excerpt": _text_excerpt(result.get("report_text"), 1400),
        }
    )
    return serialize_tool_result(payload) if payload else ""


def _ai_report_brief_lines(result: dict[str, Any], *, max_lines: int) -> list[str]:
    lines = [_tool_stage_line("AI研报", result, _reviewed_count(result))]
    if guard_line := _candidate_guard_brief_line(result.get("candidate_guard_summary")):
        lines.append(guard_line)
    lines.extend(_reviewed_symbol_lines(result, max_lines=max_lines))
    return [line for line in lines if line][:max_lines]


def _strategy_decision_brief_lines(result: dict[str, Any], *, max_lines: int) -> list[str]:
    lines = [_strategy_stage_line(result)]
    if guard_line := _candidate_guard_brief_line(result.get("candidate_guard_summary")):
        lines.append(guard_line)
    lines.extend(_reviewed_symbol_lines(result, max_lines=max_lines))
    return [line for line in lines if line][:max_lines]


def _strategy_stage_line(result: dict[str, Any]) -> str:
    parts = [
        _key_value("status", result.get("status") or result.get("reason")),
        _key_value("source", result.get("report_source")),
        _key_value("reviewed", _reviewed_count(result)),
        _key_value("next", result.get("next_action") or result.get("message")),
    ]
    detail = ", ".join(part for part in parts if part)
    return f"攻防决策: {detail}" if detail else ""


def _tool_stage_line(label: str, result: dict[str, Any], reviewed: int) -> str:
    parts = [
        _key_value("reviewed", reviewed),
        _key_value("model", result.get("model")),
        _key_value("next", result.get("next_action") or result.get("reason")),
    ]
    detail = ", ".join(part for part in parts if part)
    return f"{label}: {detail}" if detail else ""


def _candidate_guard_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "direct_buy_blocked_count": value.get("direct_buy_blocked_count"),
            "message": value.get("message"),
            "candidates": _candidate_guard_candidate_preview(value.get("candidates")),
        }
    )


def _candidate_guard_candidate_preview(value: Any) -> list[dict[str, Any]]:
    rows = _preview_list(value, 5)
    return [
        _drop_empty_preview_fields(
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "reason": row.get("reason"),
                "action_status": row.get("action_status"),
                "label_ready": row.get("label_ready"),
                "risk_factors": _preview_list(row.get("risk_factors"), 3),
                "next_step": _text_excerpt(row.get("next_step"), 120),
            }
        )
        for row in rows
        if isinstance(row, dict)
    ]


def _candidate_guard_brief_line(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    candidates = [row for row in _preview_list(value.get("candidates"), 3) if isinstance(row, dict)]
    count = value.get("direct_buy_blocked_count") or len(candidates)
    detail = "、".join(_candidate_guard_candidate_line(row) for row in candidates[:2])
    detail = detail.strip("、")
    head = f"候选护栏: {count}只禁止直接买入"
    return f"{head} · {detail}" if detail else head


def _candidate_guard_candidate_line(row: dict[str, Any]) -> str:
    name = _candidate_name(row)
    reason = _text_excerpt(row.get("reason"), 60)
    return f"{name}({reason})" if reason else name


def _key_value(key: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    return f"{key}={_text_excerpt(value, 120)}"


def _reviewed_count(result: dict[str, Any]) -> int:
    try:
        count = int(result.get("stock_count") or result.get("candidate_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count:
        return count
    return max(
        len(_preview_list(result.get("reviewed_codes"), 20)), len(_preview_list(result.get("reviewed_symbols"), 20))
    )


def _reviewed_symbol_lines(result: dict[str, Any], *, max_lines: int) -> list[str]:
    rows = _dedupe_candidate_rows(_preview_list(result.get("reviewed_symbols"), max_lines))
    return [line for row in rows if (line := _candidate_brief_line(row))]


def _screen_stocks_preview(result: dict[str, Any]) -> str:
    payload = _drop_empty_preview_fields(
        {
            "ok": result.get("ok"),
            "board": result.get("board"),
            "scan_scope": result.get("scan_scope"),
            "summary": result.get("summary"),
            "data_quality": result.get("data_quality"),
            "trade_mode": result.get("trade_mode"),
            "decision_brief": _screen_decision_preview(result.get("decision_brief")),
            "selection_brief": _screen_selection_preview(result.get("selection_brief")),
            "candidate_guard_summary": _candidate_guard_preview(result.get("candidate_guard_summary")),
            "top_candidates": _candidate_preview_list(result.get("top_candidates"), 10),
            "symbols_for_report": _candidate_preview_list(result.get("symbols_for_report"), 12),
            "action_plan": _screen_action_plan_preview(result.get("action_plan")),
            "top_sectors": _preview_list(result.get("top_sectors"), 6),
            "omitted": "完整 trigger_groups 已保留在完整结果中" if result.get("trigger_groups") else "",
        }
    )
    return serialize_tool_result(payload) if payload else ""


def _screen_stocks_brief_lines(result: dict[str, Any], *, max_lines: int) -> list[str]:
    lines: list[str] = []
    selection = result.get("selection_brief") if isinstance(result.get("selection_brief"), dict) else {}
    headline = _text_excerpt(selection.get("headline"), 120)
    if headline:
        lines.append(headline)
    if guard_line := _candidate_guard_brief_line(result.get("candidate_guard_summary")):
        lines.append(guard_line)
    for row in _screen_brief_candidates(result):
        if line := _candidate_brief_line(row):
            lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines[:max_lines]


def _screen_brief_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    selection = result.get("selection_brief") if isinstance(result.get("selection_brief"), dict) else {}
    rows: list[Any] = [selection.get("primary_pick")]
    rows.extend(_preview_list(selection.get("best_candidates"), 3))
    rows.extend(_preview_list(result.get("symbols_for_report"), 3))
    rows.extend(_preview_list(result.get("top_candidates"), 3))
    return _dedupe_candidate_rows(rows)


def _dedupe_candidate_rows(rows: list[Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("code") or row.get("summary") or row.get("name") or row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _candidate_brief_line(row: dict[str, Any]) -> str:
    name = _candidate_name(row)
    parts = [
        _action_status_label(row.get("action_status")),
        _brief_evidence(row),
        _brief_quality(row),
        _brief_risk(row),
        _brief_next_step(row),
    ]
    detail = " · ".join(part for part in parts if part)
    return f"{name} · {detail}" if detail else name


def _candidate_name(row: dict[str, Any]) -> str:
    code = str(row.get("code") or "").strip()
    name = str(row.get("name") or "").strip()
    return " ".join(part for part in (code, name) if part) or str(row.get("summary") or "候选").strip()


def _action_status_label(value: Any) -> str:
    return {
        "blocked_by_data_quality": "数据质量未过关",
        "blocked_by_market_gate": "风险闸门关闭",
        "watch_only": "观察池",
        "repair_review_only": "只做修复复核",
        "confirmation_required": "等待确认",
        "ready_for_ai_review": "可进入AI复核",
    }.get(str(value or "").strip(), "")


def _brief_risk(row: dict[str, Any]) -> str:
    risks = [str(item).strip() for item in _preview_list(row.get("risk_factors"), 2) if str(item).strip()]
    return f"风险: {'；'.join(risks)}" if risks else ""


def _brief_evidence(row: dict[str, Any]) -> str:
    parts = [
        _score_evidence("优先分", row.get("priority_score")),
        _score_evidence("动态分", row.get("shadow_score")),
        _score_evidence("触发分", row.get("score")),
        _score_evidence("漏斗分", row.get("funnel_score")),
        _grade_score_evidence("候选影子", row.get("candidate_shadow_grade"), row.get("candidate_shadow_score")),
        _grade_score_evidence("入场", row.get("entry_quality_grade"), row.get("entry_quality_score")),
        "已AI推荐" if row.get("is_ai_recommended") is True else "",
        _strategy_evidence(row.get("selection_strategy")),
    ]
    evidence = [part for part in parts if part]
    return f"证据: {'；'.join(evidence[:5])}" if evidence else ""


def _score_evidence(label: str, value: Any) -> str:
    score = _format_score(value)
    return f"{label}{score}" if score else ""


def _grade_score_evidence(label: str, grade: Any, score: Any) -> str:
    grade_text = str(grade or "").strip()
    score_text = _format_score(score)
    if grade_text and score_text:
        return f"{label}{grade_text}/{score_text}"
    if grade_text:
        return f"{label}{grade_text}"
    if score_text:
        return f"{label}{score_text}"
    return ""


def _strategy_evidence(value: Any) -> str:
    strategy = str(value or "").strip()
    return f"排序:{strategy}" if strategy else ""


def _format_score(value: Any) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(score):
        return ""
    return f"{score:.2f}".rstrip("0").rstrip(".")


def _brief_quality(row: dict[str, Any]) -> str:
    factors = [str(item).strip() for item in _preview_list(row.get("quality_factors"), 2) if str(item).strip()]
    if factors:
        return f"亮点: {'；'.join(factors)}"
    text = _text_excerpt(row.get("why") or row.get("evidence") or row.get("rank_reason"), 80)
    return f"亮点: {text}" if text else ""


def _brief_next_step(row: dict[str, Any]) -> str:
    next_step = _text_excerpt(row.get("next_step"), 80)
    return f"下一步: {next_step}" if next_step else ""


def _screen_decision_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "market_gate": value.get("market_gate"),
            "next_action": value.get("next_action"),
            "report_focus": _candidate_preview_list(value.get("report_focus"), 6),
            "watch_focus": _candidate_preview_list(value.get("watch_focus"), 6),
        }
    )


def _screen_selection_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "status": value.get("status"),
            "headline": value.get("headline"),
            "best_codes": _preview_list(value.get("best_codes"), 12),
            "primary_pick": _candidate_preview_item(value.get("primary_pick")),
            "best_candidates": _candidate_preview_list(value.get("best_candidates"), 6),
            "tool_handoff": value.get("tool_handoff"),
        }
    )


def _screen_action_plan_preview(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {
            "primary_action": value.get("primary_action"),
            "candidate_action": value.get("candidate_action"),
            "new_buy_allowed": value.get("new_buy_allowed"),
            "ai_review_allowed": value.get("ai_review_allowed"),
            "data_quality_gate": value.get("data_quality_gate"),
            "review_targets": value.get("review_targets"),
            "report_candidates": _candidate_preview_list(value.get("report_candidates"), 6),
            "watch_candidates": _candidate_preview_list(value.get("watch_candidates"), 6),
        }
    )


_CANDIDATE_PREVIEW_FIELDS = (
    "code",
    "name",
    "summary",
    "tier",
    "quality",
    "track",
    "stage",
    "candidate_lane",
    "entry_type",
    "selection_source",
    "source_type",
    "priority_rank",
    "priority_score",
    "shadow_score",
    "score",
    "selection_strategy",
    "recommend_date",
    "is_ai_recommended",
    "funnel_score",
    "recommend_count",
    "candidate_shadow_score",
    "candidate_shadow_grade",
    "entry_quality_score",
    "entry_quality_grade",
    "entry_quality_risk_flags",
    "label_ready",
    "label_status",
    "rank_reason",
    "quality_factors",
    "risk_factors",
    "action_status",
    "why",
    "evidence",
    "next_step",
    "triggers",
)


def _candidate_preview_list(value: Any, limit: int) -> list[Any]:
    rows = _preview_list(value, limit)
    return [_candidate_preview_item(row) if isinstance(row, dict) else row for row in rows]


def _candidate_preview_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty_preview_fields(
        {field: _candidate_preview_value(field, value.get(field)) for field in _CANDIDATE_PREVIEW_FIELDS}
    )


def _candidate_preview_value(field: str, value: Any) -> Any:
    if isinstance(value, list):
        return [_text_excerpt(item, 80) for item in value[:8] if str(item).strip()]
    if field in {"summary", "rank_reason", "why", "evidence", "next_step"}:
        return _text_excerpt(value, 240)
    return value


def _preview_list(value: Any, limit: int) -> list[Any]:
    return list(value[:limit]) if isinstance(value, list) else []


def _text_excerpt(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _drop_empty_preview_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != "" and value != [] and value != {}
    }
