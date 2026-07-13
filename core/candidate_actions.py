"""Shared candidate action semantics across agent and report surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateActionInfo:
    status: str
    label: str
    level: str
    blocks_direct_buy: bool = True
    allows_ai_review: bool = False


ACTION_INFO: dict[str, CandidateActionInfo] = {
    "ready_for_ai_review": CandidateActionInfo(
        "ready_for_ai_review",
        "可进入AI复核",
        "ai_review",
        blocks_direct_buy=False,
        allows_ai_review=True,
    ),
    "repair_review_only": CandidateActionInfo("repair_review_only", "只做修复复核", "review_only"),
    "repair_probe_ready": CandidateActionInfo(
        "repair_probe_ready",
        "修复确认小额试探",
        "probe_ready",
        blocks_direct_buy=False,
        allows_ai_review=True,
    ),
    "confirmation_required": CandidateActionInfo("confirmation_required", "等待确认", "confirmation"),
    "watch_only": CandidateActionInfo("watch_only", "观察池", "watch"),
    "priority_watch": CandidateActionInfo("priority_watch", "重点观察", "watch"),
    "trigger_watch": CandidateActionInfo("trigger_watch", "触发观察", "watch"),
    "caution_watch": CandidateActionInfo("caution_watch", "警戒观察", "watch"),
    "watch": CandidateActionInfo("watch", "观察", "watch"),
    "avoid": CandidateActionInfo("avoid", "回避", "blocked"),
    "blocked_by_market_gate": CandidateActionInfo("blocked_by_market_gate", "风险闸门关闭", "blocked"),
    "blocked_by_data_quality": CandidateActionInfo("blocked_by_data_quality", "数据质量未过关", "blocked"),
    "blocked_by_policy_guard": CandidateActionInfo("blocked_by_policy_guard", "策略护栏阻断", "blocked"),
    "blocked_by_quality_gate": CandidateActionInfo("blocked_by_quality_gate", "质量门槛阻断", "blocked"),
    "blocked_by_watch_only": CandidateActionInfo("blocked_by_watch_only", "仅观察阻断", "blocked"),
}


def candidate_action_info(status: Any) -> CandidateActionInfo:
    text = str(status or "").strip()
    if text in ACTION_INFO:
        return ACTION_INFO[text]
    if text.startswith("blocked_"):
        return CandidateActionInfo(text, "阻断", "blocked")
    return CandidateActionInfo(text, text, "unknown", blocks_direct_buy=False)


def candidate_action_label(status: Any) -> str:
    return candidate_action_info(status).label


def candidate_action_role(status: Any, *, guard_reason: str = "", ready_rank: int = 0, has_code: bool = True) -> str:
    text = str(status or "").strip()
    if text == "watch":
        return "观察候选"
    if text in {"priority_watch", "trigger_watch", "caution_watch", "avoid"}:
        return candidate_action_label(text)
    if text == "ready_for_ai_review":
        if not has_code:
            return "待确认候选"
        if ready_rank > 1:
            return "备选复核候选"
        return "受限复核候选" if guard_reason else "首选"
    if text == "repair_review_only":
        return "修复复核候选"
    if text == "repair_probe_ready":
        return "修复确认试探候选"
    if text == "confirmation_required":
        return "待确认候选"
    if candidate_action_info(text).level == "watch":
        return "观察候选"
    if candidate_action_info(text).level == "blocked":
        return "阻断候选"
    return "候选"


def candidate_direct_buy_allowed(row: dict[str, Any]) -> bool:
    if "direct_buy_allowed" in row:
        return _is_true(row.get("direct_buy_allowed"))
    info = candidate_action_info(row.get("action_status") or row.get("status"))
    if info.blocks_direct_buy:
        return False
    if row.get("label_ready") is False:
        return False
    if not _is_true(row.get("new_buy_allowed")):
        return False
    readiness = str(row.get("trade_readiness") or "").strip()
    return readiness not in {"research_only", "review_only", "observe_only"}


def candidate_action_fields(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("action_status") or row.get("status") or "").strip()
    info = candidate_action_info(status)
    return {
        "action_status": status,
        "action_label": info.label,
        "action_level": info.level,
        "direct_buy_allowed": candidate_direct_buy_allowed(row),
    }


def candidate_action_blocks_direct_buy(status: Any) -> bool:
    return candidate_action_info(status).blocks_direct_buy


def _is_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no", "n"}
    return value == 0


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value is True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return value == 1
