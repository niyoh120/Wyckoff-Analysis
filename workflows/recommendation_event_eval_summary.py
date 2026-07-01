"""Shared summaries for recommendation event evaluation results."""

from __future__ import annotations

from typing import Any


def recommendation_event_eval_result_summary(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    all_rows = summary.get("all") if isinstance(summary.get("all"), dict) else {}
    decision = summary.get("ranking_decision") if isinstance(summary.get("ranking_decision"), dict) else {}
    selection = result.get("policy_selection") if isinstance(result.get("policy_selection"), dict) else {}
    status = str(decision.get("status") or "unknown")
    strategy = str(decision.get("recommended_strategy") or decision.get("watch_strategy") or "score_only")
    top_k = decision.get("recommended_top_k") or "n/a"
    ready = f"{all_rows.get('rows_ready', 0)}/{all_rows.get('rows_total', 0)}"
    lines = [
        f"推荐事件评估: ready={ready}, hit={_summary_pct(all_rows.get('hit_rate_pct'))}%, ranking_decision={status}",
        _ranking_decision_line(status, strategy, top_k),
    ]
    if pick_line := _policy_selection_summary_line(selection):
        lines.append(pick_line)
    reason = str(decision.get("reason") or "").strip()
    if reason:
        lines.append(f"reason: {reason}")
    return "\n".join(line for line in lines if line)


def _ranking_decision_line(status: str, strategy: str, top_k: Any) -> str:
    if status == "candidate":
        return f"排序接入候选: {strategy} top{top_k} 已通过样本/lift/风险门槛"
    if status == "watch":
        return f"排序观察项: {strategy} 有改善但未全部过门槛"
    return "排序策略: 继续保持 score_only"


def _policy_selection_summary_line(selection: dict[str, Any]) -> str:
    picks = selection.get("picks") if isinstance(selection.get("picks"), list) else []
    names = [_pick_summary_name(pick) for pick in picks if isinstance(pick, dict)]
    names = [name for name in names if name]
    if not names:
        return ""
    action_plan = selection.get("action_plan") if isinstance(selection.get("action_plan"), dict) else {}
    strategy = str(selection.get("selection_strategy") or "score_only")
    rec_date = selection.get("recommend_date") or "-"
    parts = [
        f"最新候选({rec_date}, {strategy}): {', '.join(names[:5])}",
        f"状态={_selection_status_text(selection, action_plan)}",
    ]
    if reason := _brief_reason(action_plan.get("reason") or selection.get("reason")):
        parts.append(f"原因={reason}")
    return "；".join(parts)


def _pick_summary_name(pick: dict[str, Any]) -> str:
    name = _pick_name(pick)
    score = _summary_pct(pick.get("risk_adjusted_quality_score"))
    return f"{name}(风险调整分{score})" if name and score != "n/a" else name


def _selection_status_text(selection: dict[str, Any], action_plan: dict[str, Any]) -> str:
    if action_plan.get("ai_review_allowed"):
        return "可进入AI研报"
    status = str(selection.get("status") or action_plan.get("review_status") or "watch").strip()
    if status in {"watch", "keep_score_only", "insufficient_sample", "watch_only"}:
        return "只读观察"
    return status or "只读观察"


def _brief_reason(raw: Any, limit: int = 90) -> str:
    text = str(raw or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _pick_name(pick: dict[str, Any]) -> str:
    code = str(pick.get("code") or "").strip()
    name = str(pick.get("name") or "").strip()
    return " ".join(part for part in (code, name) if part)


def _summary_pct(raw: Any) -> str:
    try:
        return f"{float(raw):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "n/a"
