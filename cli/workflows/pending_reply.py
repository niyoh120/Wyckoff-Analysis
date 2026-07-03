"""Model-assisted classification for replies to pending workflow approvals."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_VALID_INTENTS = {"approve", "deny", "revise", "chat"}
_INTENT_FIELDS = ("intent", "action", "mode", "decision", "reply_intent")
_MAX_SUMMARY_STEPS = 6
_MIN_COMMIT_CONFIDENCE = 0.45

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

    if provider is None or not str(text or "").strip():
        return ""
    try:
        response = _provider_response(provider, [{"role": "user", "content": _reply_prompt(text, run)}])
        decision = _parse_decision(response)
    except Exception:
        logger.debug("pending workflow reply router failed", exc_info=True)
        return ""
    if not decision:
        return ""
    intent = str(decision.get("intent") or "")
    if intent in {"approve", "deny"} and float(decision.get("confidence") or 0.0) < _MIN_COMMIT_CONFIDENCE:
        return ""
    return intent if intent in _VALID_INTENTS else ""


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
    text = _collect_stream_text(provider.chat_stream(messages, [], _PENDING_REPLY_SYSTEM_PROMPT))
    return {"type": "text", "text": text} if text else None


def _collect_stream_text(chunks: Any) -> str:
    parts: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        if chunk.get("type") == "tool_calls":
            return ""
        if chunk.get("type") == "text_delta":
            parts.append(str(chunk.get("text", "")))
    return "".join(parts).strip()


def _parse_decision(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict) or response.get("type") == "tool_calls":
        return None
    try:
        payload = _loads_json(str(response.get("text") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    intent = _decision_intent(payload)
    if intent not in _VALID_INTENTS:
        return None
    return {
        "intent": intent,
        "confidence": _decision_confidence(payload),
        "reason": str(payload.get("reason") or "").strip()[:120],
    }


def _loads_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("pending workflow reply decision must be an object")
    return payload


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


def _decision_confidence(payload: dict[str, Any]) -> float:
    raw = payload.get("confidence", payload.get("score", payload.get("probability", 0.0)))
    try:
        value = float(str(raw).strip().rstrip("%"))
    except (TypeError, ValueError):
        return 0.0
    if value > 1.0:
        value /= 100.0
    return round(max(0.0, min(value, 1.0)), 4)
