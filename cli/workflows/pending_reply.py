"""Model-assisted classification for replies to pending workflow approvals."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from cli.workflows._shared import (
    collect_stream_text,
    decision_confidence,
    loads_json,
)

logger = logging.getLogger(__name__)

_VALID_INTENTS = {"approve", "deny", "revise", "chat"}
_INTENT_FIELDS = ("intent", "action", "mode", "decision", "reply_intent")
_MAX_SUMMARY_STEPS = 6
_MIN_COMMIT_CONFIDENCE = 0.45
_APPROVE_REPLIES = {
    "go",
    "ok",
    "y",
    "yes",
    "可以",
    "好",
    "好的",
    "开始",
    "开始吧",
    "继续",
    "继续吧",
    "跑",
    "跑吧",
    "运行",
    "执行",
    "执行吧",
    "确认",
    "没问题",
    "可以跑",
    "就这样",
    "按这个来",
}
_DENY_REPLIES = {
    "n",
    "no",
    "不用",
    "不用了",
    "不要",
    "先不要",
    "不要了",
    "不用workflow",
    "不要workflow",
    "先不用workflow",
    "取消",
    "取消吧",
    "算了",
}
_APPROVE_MARKERS = (
    "开始",
    "运行",
    "执行",
    "继续",
    "跑一下",
    "跑起来",
    "可以跑",
    "可以执行",
    "可以运行",
    "按这个",
    "就这样",
    "直接走",
    "没问题",
    "同意",
    "确认",
)
_DENY_MARKERS = (
    "不可以",
    "不能",
    "先不要",
    "不要跑",
    "不要执行",
    "不要运行",
    "别跑",
    "别执行",
    "别运行",
    "先别",
    "拒绝",
    "取消",
)
_QUESTION_MARKERS = ("要不要", "可不可以", "能不能", "是否")
_REVISION_MARKERS = (
    "修改",
    "改成",
    "调整",
    "换成",
    "删掉",
    "删除",
    "去掉",
    "加上",
    "增加",
    "补上",
    "合并",
    "拆开",
    "重排",
    "太死板",
)
_REVISION_SOFT_MARKERS = ("不要", "不用", "别", "先", "直接", "只")
_REVISION_OBJECT_MARKERS = (
    "扫",
    "筛",
    "候选",
    "票",
    "标的",
    "持仓",
    "研报",
    "攻防",
    "回测",
    "步骤",
    "任务",
    "task",
    "工具",
    "计划",
    "拆",
)
_REVISION_QUESTION_MARKERS = ("解释", "说明", "为什么", "是什么", "啥意思", "怎么用")

_PENDING_REPLY_SYSTEM_PROMPT = """\
你是 Wyckoff CLI 的 pending workflow 回复路由器。用户只会在 agent 内聊天。

只判断用户这句话是在处理一个“待批准 workflow”，不要执行 workflow，不要改写计划。

intent 只能是:
- approve: 用户明确要按当前 workflow 开始/继续/运行。
- deny: 用户明确取消、不跑、先不要。
- revise: 用户在反馈要修改 workflow 的范围、步骤、工具、顺序或输出。
- chat: 用户只是提问、闲聊、表达犹豫，或者不足以批准/取消/修订。

口语、省略、错别字和不标准说法按语义判断；不要只按固定关键词。
只有明确同意运行时才 approve；只有明确取消时才 deny；有任何修改意见优先 revise。

只输出 JSON:
{"intent":"approve|deny|revise|chat","confidence":0.0,"reason":"简短中文原因"}
"""


def route_pending_workflow_reply(text: str, provider: Any | None, run: Any | None = None) -> str:
    """Classify a chat reply for a single pending workflow."""

    if not str(text or "").strip():
        return ""
    decision = _model_decision(text, provider, run) if provider is not None else None
    if not decision:
        return classify_pending_workflow_reply(text)
    intent = str(decision.get("intent") or "")
    if intent in {"approve", "deny"} and float(decision.get("confidence") or 0.0) < _MIN_COMMIT_CONFIDENCE:
        return classify_pending_workflow_reply(text)
    return intent if intent in _VALID_INTENTS else ""


def classify_pending_workflow_reply(text: str) -> str:
    """Best-effort local semantic fallback for pending workflow replies."""

    normalized = _normalize_reply(text)
    if not normalized:
        return ""
    if is_pending_workflow_revision(text):
        return "revise"
    if _question_like(normalized):
        return "chat"
    if normalized in _APPROVE_REPLIES:
        return "approve"
    if normalized in _DENY_REPLIES:
        return "deny"
    if any(marker in normalized for marker in _DENY_MARKERS):
        return "deny"
    if any(marker in normalized for marker in _APPROVE_MARKERS):
        return "approve"
    return ""


def is_pending_workflow_revision(text: str) -> bool:
    normalized = _normalize_reply(text)
    if not normalized:
        return False
    if "workflow" in normalized and any(marker in normalized for marker in _REVISION_QUESTION_MARKERS):
        return False
    if any(marker in normalized for marker in _REVISION_MARKERS):
        return True
    return any(marker in normalized for marker in _REVISION_SOFT_MARKERS) and any(
        marker in normalized for marker in _REVISION_OBJECT_MARKERS
    )


def _model_decision(text: str, provider: Any, run: Any | None) -> dict[str, Any] | None:
    try:
        response = _provider_response(provider, [{"role": "user", "content": _reply_prompt(text, run)}])
        return _parse_decision(response)
    except Exception:
        logger.debug("pending workflow reply router failed", exc_info=True)
        return None


def _reply_prompt(text: str, run: Any | None) -> str:
    return (
        f"用户回复:\n{text}\n\n"
        f"待批准 workflow 摘要:\n{json.dumps(_run_summary(run), ensure_ascii=False, default=str)}\n\n"
        "请只输出分类 JSON。"
    )


def _run_summary(run: Any | None) -> dict[str, Any]:
    payload = _run_payload(run)
    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else payload
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    return {
        "run_id": payload.get("run_id") or getattr(run, "run_id", ""),
        "label": payload.get("label") or getattr(run, "label", ""),
        "workflow": payload.get("workflow") or getattr(run, "workflow", ""),
        "steps": [_step_summary(step) for step in steps[:_MAX_SUMMARY_STEPS] if isinstance(step, dict)],
    }


def _run_payload(run: Any | None) -> dict[str, Any]:
    if run is None:
        return {}
    if isinstance(run, dict):
        return run
    plan_payload = getattr(run, "plan_payload", None)
    if callable(plan_payload):
        value = plan_payload()
        return value if isinstance(value, dict) else {}
    return {}


def _step_summary(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": step.get("step_id") or step.get("id"),
        "title": step.get("title"),
        "tools": step.get("tool_scope") or step.get("effective_tool_scope") or step.get("tools"),
    }


def _provider_response(provider: Any, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    if hasattr(provider, "chat"):
        try:
            return provider.chat(messages, [], _PENDING_REPLY_SYSTEM_PROMPT)
        except NotImplementedError:
            if not getattr(provider, "use_chat_stream_for_pending_reply", False):
                return None
    if not hasattr(provider, "chat_stream"):
        return None
    text = collect_stream_text(provider.chat_stream(messages, [], _PENDING_REPLY_SYSTEM_PROMPT))
    return {"type": "text", "text": text} if text else None


def _parse_decision(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict) or response.get("type") == "tool_calls":
        return None
    try:
        payload = loads_json(str(response.get("text") or ""), error_label="pending workflow reply decision")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    intent = _decision_intent(payload)
    if intent not in _VALID_INTENTS:
        return None
    return {
        "intent": intent,
        "confidence": decision_confidence(payload),
        "reason": str(payload.get("reason") or "").strip()[:120],
    }


def _decision_intent(payload: dict[str, Any]) -> str:
    for field in _INTENT_FIELDS:
        if intent := _intent_value(payload.get(field)):
            return intent
    return ""


def _intent_value(value: Any) -> str:
    text = re.sub(r"[\s/-]+", "_", str(value or "").strip().lower()).strip("_")
    return {
        "accept": "approve",
        "accepted": "approve",
        "approved": "approve",
        "run": "approve",
        "start": "approve",
        "cancel": "deny",
        "reject": "deny",
        "rejected": "deny",
        "stop": "deny",
        "edit": "revise",
        "modify": "revise",
        "revision": "revise",
        "question": "chat",
        "ask": "chat",
    }.get(text, text)


def _normalize_reply(text: str) -> str:
    return re.sub(r"[\s。！!,.，、？?]+", "", str(text or "").lower())


def _question_like(normalized: str) -> bool:
    return normalized.endswith(("吗", "么", "嘛")) or any(marker in normalized for marker in _QUESTION_MARKERS)
