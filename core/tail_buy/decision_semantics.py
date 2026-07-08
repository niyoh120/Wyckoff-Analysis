from __future__ import annotations

from typing import Any

from core.tail_buy.models import DECISION_BUY, DECISION_SKIP, DECISION_WATCH

HIGH_RISK_MOMENTUM_SIGNALS = {"rec_momentum_continuation"}


def is_limit_up_candidate(features: dict[str, Any] | None) -> bool:
    """当日触及/收于涨停：现价无法按挂单价买入，需与普通可挂单信号区分展示。"""
    row = features or {}
    return bool(row.get("limit_up_touched")) or bool(row.get("limit_up_closed"))


def tail_buy_execution_semantics(
    final_decision: Any,
    signal_type: Any = "",
    *,
    report_mode: str = "intraday",
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = str(final_decision or "").strip().upper()
    signal = str(signal_type or "").strip()
    fallback = (
        _post_close_semantics(decision)
        if report_mode == "post_close_review"
        else _intraday_semantics(decision, signal, features)
    )
    row = features or {}
    return {
        "execution_label": str(row.get("execution_label") or fallback["execution_label"]),
        "execution_status": str(row.get("execution_status") or fallback["execution_status"]),
        "orderable": row.get("orderable") if isinstance(row.get("orderable"), bool) else fallback["orderable"],
        "execution_next_step": str(row.get("execution_next_step") or fallback["execution_next_step"]),
    }


def _intraday_semantics(decision: str, signal: str, features: dict[str, Any] | None = None) -> dict[str, Any]:
    if decision == DECISION_BUY and is_limit_up_candidate(features):
        return _semantics("观察买入", "watch_buy", False, "当日已触及/收于涨停，现价无法按挂单价买入；只保留人工复核。")
    if decision == DECISION_BUY and signal in HIGH_RISK_MOMENTUM_SIGNALS:
        return _semantics("观察买入", "watch_buy", False, "高位动能默认不买；只保留人工复核。")
    if decision == DECISION_BUY:
        return _semantics("可执行买入", "executable_buy", True, "仍需人工按支撑、回落与仓位纪律复核。")
    if decision == DECISION_WATCH:
        return _semantics("观察买入", "watch_buy", False, "继续观察，未达到直接开仓口径。")
    if decision == DECISION_SKIP:
        return _semantics("禁止新仓", "blocked", False, "暂不买入。")
    return _semantics("未知", "unknown", False, "决策缺失或无法识别。")


def _post_close_semantics(decision: str) -> dict[str, Any]:
    if decision == DECISION_BUY:
        return _semantics("明日观察买入", "next_day_watch", False, "明日仍需开盘/尾盘确认后再决定。")
    if decision == DECISION_WATCH:
        return _semantics("明日观察", "next_day_watch", False, "继续观察，等待次日确认。")
    if decision == DECISION_SKIP:
        return _semantics("明日放弃", "blocked", False, "明日不纳入开仓计划。")
    return _semantics("未知", "unknown", False, "决策缺失或无法识别。")


def _semantics(label: str, status: str, orderable: bool, next_step: str) -> dict[str, Any]:
    return {
        "execution_label": label,
        "execution_status": status,
        "orderable": orderable,
        "execution_next_step": next_step,
    }
