"""Agent-facing recommendation evaluation tools."""

from __future__ import annotations

import logging
import re
from typing import Any

from agents.tool_context import ToolContext
from core.candidate_guards import policy_candidate_guard_summary
from core.candidate_quality import risk_adjusted_quality_metrics

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = (1, 3, 5)
_MAX_TOP_K = 20


def evaluate_recommendation_events(
    market: str = "cn",
    horizon_days: int = 5,
    target_pct: float = 10.0,
    max_dates: int = 30,
    kline_count: int = 160,
    top_k: list[int] | str | int | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Evaluate recent recommendation rows and return the current policy picks."""

    _ = tool_context
    try:
        from workflows.recommendation_event_eval import RecommendationEventEvalRequest, build_recommendation_event_eval
        from workflows.recommendation_event_eval_summary import recommendation_event_eval_result_summary

        request = RecommendationEventEvalRequest(
            market=str(market or "cn").strip() or "cn",
            horizon_days=max(int(horizon_days), 1),
            target_pct=max(float(target_pct), 0.1),
            max_dates=max(int(max_dates), 1),
            kline_count=max(int(kline_count), 1),
            top_k=_normalize_top_k(top_k),
        )
        result = build_recommendation_event_eval(request)
        guard_summary = policy_candidate_guard_summary(result.get("policy_selection"), result)
        payload = {
            "ok": True,
            "job_kind": "recommendation_event_eval",
            "result_summary": recommendation_event_eval_result_summary(result),
            "metadata": result["metadata"],
            "summary": result["summary"],
            "policy_selection": result.get("policy_selection", {}),
            "daily": result["daily"],
        }
        if guard_summary:
            payload["candidate_guard_summary"] = guard_summary
        remember_recommendation_event_eval(tool_context, payload)
        return payload
    except Exception as exc:
        logger.exception("evaluate_recommendation_events error")
        return {
            "error": str(exc),
            "hint": "需要 SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY 和 TICKFLOW_API_KEY 可用，且推荐追踪表存在近期记录。",
        }


def _normalize_top_k(raw: list[int] | str | int | None) -> tuple[int, ...]:
    if raw in (None, ""):
        return _DEFAULT_TOP_K
    values = _top_k_values(raw)
    normalized = sorted({min(max(int(value), 1), _MAX_TOP_K) for value in values})
    return tuple(normalized) or _DEFAULT_TOP_K


def _top_k_values(raw: list[int] | str | int) -> list[int]:
    if isinstance(raw, str):
        return [int(item) for item in re.split(r"[,\s]+", raw.strip()) if item]
    if isinstance(raw, (list, tuple)):
        return [int(item) for item in raw]
    return [int(raw)]


def remember_recommendation_event_eval(tool_context: ToolContext | None, result: dict[str, Any]) -> None:
    if tool_context is None or result.get("error"):
        return
    tool_context.state["last_recommendation_event_eval"] = _compact_recommendation_eval(result)
    screen_handoff = _recommendation_eval_screen_handoff(result)
    if screen_handoff:
        tool_context.state["last_screen_result"] = screen_handoff


def _compact_recommendation_eval(result: dict[str, Any]) -> dict[str, Any]:
    policy_selection = _compact_policy_selection(result.get("policy_selection"))
    return {
        "ok": result.get("ok"),
        "job_kind": result.get("job_kind"),
        "result_summary": result.get("result_summary", ""),
        "metadata": result.get("metadata", {}),
        "summary": result.get("summary", {}),
        "policy_selection": policy_selection,
        "candidate_guard_summary": policy_candidate_guard_summary(policy_selection, result),
        "daily": list(result.get("daily") or [])[:10],
    }


def _compact_policy_selection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload = dict(value)
    payload["picks"] = [
        pick
        for row in list(value.get("picks") or [])[:10]
        if isinstance(row, dict)
        if (pick := _policy_pick_handoff(row))
    ]
    return payload


def _recommendation_eval_screen_handoff(result: dict[str, Any]) -> dict[str, Any]:
    selection = _compact_policy_selection(result.get("policy_selection"))
    picks = selection.get("picks") if isinstance(selection.get("picks"), list) else []
    if not picks:
        return {}
    codes = [row["code"] for row in picks if row.get("code")]
    headline = _policy_handoff_headline(selection, picks)
    action_plan = _selection_action_plan(selection, picks, codes)
    review_status = _selection_review_status(action_plan, picks)
    report_candidates = picks if action_plan["ai_review_allowed"] else []
    watch_candidates = [] if action_plan["ai_review_allowed"] else picks
    guard_summary = policy_candidate_guard_summary(selection, result)
    return {
        "ok": True,
        "board": str((result.get("metadata") or {}).get("market") or "cn"),
        "scan_scope": {"source": "recommendation_event_eval", "recommend_date": selection.get("recommend_date")},
        "summary": _policy_handoff_summary(result, len(report_candidates), len(watch_candidates)),
        "decision_brief": {
            "market_gate": "recommendation_event_eval",
            "next_action": action_plan["next_step"],
            "report_focus": report_candidates,
            "watch_focus": watch_candidates,
        },
        "selection_brief": {
            "status": review_status,
            "headline": headline,
            "best_codes": codes,
            "primary_pick": picks[0],
            "best_candidates": picks,
            "tool_handoff": _selection_next_tool(action_plan),
        },
        "action_plan": _screen_action_plan(action_plan, codes, review_status, report_candidates, watch_candidates),
        "candidate_guard_summary": guard_summary,
        "top_candidates": picks,
        "symbols_for_report": report_candidates,
        "report_candidates": report_candidates,
        "watch_candidates": watch_candidates,
    }


def _selection_action_plan(selection: dict[str, Any], picks: list[dict[str, Any]], codes: list[str]) -> dict[str, Any]:
    source = selection.get("action_plan") if isinstance(selection.get("action_plan"), dict) else {}
    ai_review_allowed = bool(source.get("ai_review_allowed")) and bool(codes)
    return {
        "primary_action": str(
            source.get("primary_action")
            or ("generate_ai_report" if ai_review_allowed else "watch_latest_policy_selection")
        ),
        "candidate_action": str(
            source.get("candidate_action") or ("generate_ai_report" if ai_review_allowed else "watch_only")
        ),
        "new_buy_allowed": False,
        "ai_review_allowed": ai_review_allowed,
        "trade_readiness": str(source.get("trade_readiness") or "research_only"),
        "review_status": str(source.get("review_status") or _pick_review_status(picks, ai_review_allowed)),
        "reason": str(source.get("reason") or "来自推荐事件评估的最新只读 policy_selection"),
        "next_step": str(source.get("next_step") or _pick_next_step(picks)),
        "next_tool": source.get("next_tool") if isinstance(source.get("next_tool"), dict) else {},
    }


def _screen_action_plan(
    action_plan: dict[str, Any],
    codes: list[str],
    review_status: str,
    report_candidates: list[dict[str, Any]],
    watch_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    review_targets = {
        "codes": codes,
        "status": review_status,
        "reason": action_plan["reason"],
        "report_candidates": report_candidates,
        "watch_candidates": watch_candidates,
    }
    if next_tool := _selection_next_tool(action_plan):
        review_targets.update({"tool": next_tool["tool"], "args": next_tool.get("args", {})})
    return {
        "primary_action": action_plan["primary_action"],
        "candidate_action": action_plan["candidate_action"],
        "new_buy_allowed": False,
        "ai_review_allowed": action_plan["ai_review_allowed"],
        "trade_readiness": action_plan["trade_readiness"],
        "reason": action_plan["reason"],
        "next_step": action_plan["next_step"],
        "review_targets": review_targets,
        "report_candidates": report_candidates,
        "watch_candidates": watch_candidates,
    }


def _selection_review_status(action_plan: dict[str, Any], picks: list[dict[str, Any]]) -> str:
    status = str(action_plan.get("review_status") or "").strip()
    if status:
        return status
    return _pick_review_status(picks, bool(action_plan.get("ai_review_allowed")))


def _pick_review_status(picks: list[dict[str, Any]], ai_review_allowed: bool) -> str:
    if ai_review_allowed:
        return "ready_for_ai_review"
    first = picks[0] if picks else {}
    return str(first.get("action_status") or "watch_only")


def _selection_next_tool(action_plan: dict[str, Any]) -> dict[str, Any]:
    if not action_plan.get("ai_review_allowed"):
        return {}
    next_tool = action_plan.get("next_tool") if isinstance(action_plan.get("next_tool"), dict) else {}
    return dict(next_tool) if next_tool.get("tool") else {}


def _pick_next_step(picks: list[dict[str, Any]]) -> str:
    first = picks[0] if picks else {}
    return str(first.get("next_step") or "先作为观察候选复核，等待更多样本或研报证据后再升级")


def _policy_pick_handoff(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("code") or "").strip()
    if not code:
        return {}
    strategy = str(row.get("selection_strategy") or "").strip()
    rank = row.get("rank")
    quality_factors = _policy_quality_factors(row)
    quality_metrics = _policy_quality_metrics(row)
    return {
        "code": code,
        "name": str(row.get("name") or code).strip(),
        "tag": "推荐评估候选",
        "selection_source": "recommendation_event_eval",
        "source_type": "policy_selection",
        "priority_rank": rank,
        "rank_reason": _policy_rank_reason(rank, strategy, quality_factors),
        "quality_factors": quality_factors,
        "risk_factors": _policy_risk_factors(row),
        "action_status": str(row.get("action_status") or "ready_for_ai_review"),
        "next_step": str(row.get("next_step") or "生成 AI 研报并结合持仓形成攻防决策"),
        "selection_strategy": strategy,
        "recommend_date": row.get("recommend_date"),
        "is_ai_recommended": row.get("is_ai_recommended"),
        "funnel_score": row.get("funnel_score"),
        "recommend_count": row.get("recommend_count"),
        "candidate_shadow_score": row.get("candidate_shadow_score"),
        "candidate_shadow_grade": row.get("candidate_shadow_grade"),
        "entry_quality_score": row.get("entry_quality_score"),
        "entry_quality_grade": row.get("entry_quality_grade"),
        "entry_quality_risk_flags": row.get("entry_quality_risk_flags") or [],
        **quality_metrics,
        "label_ready": row.get("label_ready"),
        "label_status": row.get("label_status"),
    }


def _policy_quality_factors(row: dict[str, Any]) -> list[str]:
    factors = [str(item).strip() for item in row.get("quality_factors") or [] if str(item).strip()]
    if grade := str(row.get("candidate_shadow_grade") or "").strip():
        factors.append(f"候选影子评级 {grade}")
    if grade := str(row.get("entry_quality_grade") or "").strip():
        factors.append(f"入场质量评级 {grade}")
    if row.get("is_ai_recommended") is True:
        factors.append("已进入 AI 推荐")
    return list(dict.fromkeys(factors))


def _policy_risk_factors(row: dict[str, Any]) -> list[str]:
    risks = [str(item).strip() for item in row.get("risk_factors") or [] if str(item).strip()]
    risks.extend(str(item).strip() for item in row.get("entry_quality_risk_flags") or [] if str(item).strip())
    if row.get("label_ready") is False:
        risks.append("评估标签尚未成熟")
    return list(dict.fromkeys(risks))


def _policy_quality_metrics(row: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = risk_adjusted_quality_metrics(row)
    for field in ("candidate_quality_score", "risk_adjusted_quality_score", "entry_risk_penalty"):
        if row.get(field) not in (None, "", []):
            metrics[field] = row[field]
    return metrics


def _policy_rank_reason(rank: Any, strategy: str, quality_factors: list[str]) -> str:
    parts = [f"推荐评估候选#{rank}" if rank else "推荐评估候选"]
    if strategy:
        parts.append(strategy)
    parts.extend(quality_factors[:2])
    return "；".join(parts)


def _policy_handoff_headline(selection: dict[str, Any], picks: list[dict[str, Any]]) -> str:
    strategy = str(selection.get("selection_strategy") or "score_only")
    rec_date = selection.get("recommend_date") or "-"
    names = ", ".join(_pick_name(row) for row in picks[:5])
    return f"最新推荐评估候选({rec_date}, {strategy}): {names}"


def _policy_handoff_summary(
    result: dict[str, Any],
    report_candidate_count: int,
    watch_candidate_count: int,
) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    all_rows = summary.get("all") if isinstance(summary.get("all"), dict) else {}
    decision = summary.get("ranking_decision") if isinstance(summary.get("ranking_decision"), dict) else {}
    return {
        "source": "recommendation_event_eval",
        "report_candidates": report_candidate_count,
        "watch_candidates": watch_candidate_count,
        "rows_ready": all_rows.get("rows_ready", 0),
        "rows_total": all_rows.get("rows_total", 0),
        "hit_rate_pct": all_rows.get("hit_rate_pct"),
        "ranking_decision": decision.get("status", "unknown"),
    }


def _pick_name(row: dict[str, Any]) -> str:
    code = str(row.get("code") or "").strip()
    name = str(row.get("name") or "").strip()
    return " ".join(part for part in (code, name) if part)
