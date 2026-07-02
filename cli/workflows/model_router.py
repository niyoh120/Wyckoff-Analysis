"""Model-assisted workflow routing for natural-language turns."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from typing import Any

from cli.workflows.models import WorkflowContext
from cli.workflows.router import WORKFLOWS, route_resume_workflow, route_workflow

logger = logging.getLogger(__name__)

_MAX_REASON_CHARS = 120
_VALID_MODES = {"direct", "dynamic_workflow"}
_MODE_FIELDS = ("mode", "route", "runtime", "execution_mode", "execution", "answer_mode", "plan_mode")
_MODE_VALUE_FIELDS = ("mode", "name", "value", "route", "runtime", "execution_mode", "execution", "type", "kind")
_DECISION_CONTAINER_FIELDS = ("decision", "routing", "router", "result", "selection", "choice", "classification")
_WORKFLOW_FLAG_FIELDS = (
    "workflow",
    "use_workflow",
    "dynamic_workflow",
    "needs_workflow",
    "needs_plan",
    "use_plan",
    "requires_plan",
    "needs_steps",
    "multi_step",
    "multi_stage",
)
_MODE_ALIASES = {
    "direct": {
        "answer",
        "chat",
        "general",
        "general_chat",
        "normal",
        "single",
        "single_step",
        "直接",
        "直接回答",
        "直接处理",
        "普通对话",
        "普通聊天",
        "直答",
    },
    "dynamic_workflow": {
        "agentic",
        "background",
        "dynamic",
        "dynamic workflow",
        "multi_stage",
        "multi_step",
        "parallel",
        "plan",
        "planned",
        "workflow",
        "work_flow",
        "多阶段",
        "拆分执行",
        "动态 workflow",
        "动态任务",
        "动态工作流",
        "工作流",
        "计划执行",
    },
}

_ROUTER_SYSTEM_PROMPT = """\
你是 Wyckoff CLI 的 runtime router。用户只会在 agent 内聊天。

只选择本轮执行模式，不改写、不解释、不确认用户请求。
默认用 direct；只有需要持久化计划、并发/后台执行、跨对象复核或多阶段交付时，才用 dynamic_workflow。
confidence 只表示把握度，不会覆盖 mode 判断。

只输出 JSON:
{"mode":"direct|dynamic_workflow","confidence":0.0,"reason":"简短中文原因"}
"""


def route_workflow_with_model(user_text: str, provider: Any | None) -> WorkflowContext:
    """Use the model as the primary semantic router when it is available."""

    resumed = route_resume_workflow(user_text)
    if resumed:
        return resumed
    fallback_context = route_workflow(user_text)
    decision, fallback_reason = _model_decision(user_text, provider)
    if decision:
        return _context_from_model_decision(decision, fallback_context)
    return _context_with_router_fallback(fallback_context, fallback_reason)


def _context_from_model_decision(decision: dict[str, Any], fallback_context: WorkflowContext) -> WorkflowContext:
    if _direct_model_conflicts_with_required_workflow(decision, fallback_context):
        return _required_workflow_context(decision, fallback_context)
    return replace(
        WORKFLOWS["dynamic_task"] if _should_use_workflow(decision) else WORKFLOWS["general_chat"],
        route_reason=_model_route_reason(decision),
        route_confidence=float(decision["confidence"]),
        route_matches=("model_router",),
    )


def _direct_model_conflicts_with_required_workflow(decision: dict[str, Any], fallback_context: WorkflowContext) -> bool:
    return not _should_use_workflow(decision) and fallback_context.route_reason == "明显的多阶段选股任务"


def _required_workflow_context(decision: dict[str, Any], fallback_context: WorkflowContext) -> WorkflowContext:
    matches = tuple(dict.fromkeys(("model_router_guard", *fallback_context.route_matches)))
    return replace(
        fallback_context,
        route_reason=f"模型判断 direct，但本地兜底识别为多阶段选股任务：{decision['reason']}",
        route_confidence=max(float(decision["confidence"]), fallback_context.route_confidence),
        route_matches=matches,
    )


def _model_route_reason(decision: dict[str, Any]) -> str:
    if _should_use_workflow(decision):
        return f"模型判断需要动态 workflow：{decision['reason']}"
    return f"模型判断直接处理：{decision['reason']}"


def _model_decision(user_text: str, provider: Any | None) -> tuple[dict[str, Any] | None, str]:
    if provider is None:
        return None, "provider_unavailable"
    messages = [{"role": "user", "content": f"用户请求:\n{user_text}\n\n请输出 routing JSON。"}]
    try:
        response = _router_response(provider, messages)
        if response is None:
            return None, "router_response_unavailable"
        decision = _parse_decision(response)
        if decision is None:
            return None, "invalid_router_decision"
        return decision, ""
    except Exception:
        logger.debug("model workflow router failed", exc_info=True)
        return None, "router_error"


def _context_with_router_fallback(context: WorkflowContext, fallback_reason: str) -> WorkflowContext:
    if not fallback_reason:
        return context
    reason = _fallback_route_reason(context, fallback_reason)
    matches = tuple(dict.fromkeys(("model_router_fallback", *context.route_matches)))
    return replace(context, route_reason=reason, route_matches=matches)


def _fallback_route_reason(context: WorkflowContext, fallback_reason: str) -> str:
    label = _fallback_reason_label(fallback_reason)
    if context.is_general:
        return f"模型路由不可用（{label}），直接 agent 处理"
    return f"模型路由不可用（{label}），沿用兜底路由：{context.route_reason}"


def _fallback_reason_label(reason: str) -> str:
    return {
        "provider_unavailable": "无 provider",
        "router_response_unavailable": "无路由响应",
        "invalid_router_decision": "路由 JSON 无效",
        "router_error": "调用异常",
    }.get(reason, "未知原因")


def _router_response(provider: Any, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    if hasattr(provider, "chat"):
        try:
            return provider.chat(messages, [], _ROUTER_SYSTEM_PROMPT)
        except NotImplementedError:
            if not getattr(provider, "use_chat_stream_for_routing", False):
                return None
    if not hasattr(provider, "chat_stream"):
        return None
    text = _collect_stream_text(provider.chat_stream(messages, [], _ROUTER_SYSTEM_PROMPT))
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
    payload = _router_decision_payload(payload)
    mode = _decision_mode(payload)
    if not mode:
        return None
    confidence = _decision_confidence(payload)
    return {
        "mode": mode,
        "confidence": confidence,
        "reason": _clean_reason(payload.get("reason")),
    }


def _router_decision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if _payload_has_decision_value(payload):
        return payload
    for field in _DECISION_CONTAINER_FIELDS:
        nested = payload.get(field)
        if isinstance(nested, dict):
            merged = dict(payload)
            merged.update(nested)
            return merged
    return payload


def _payload_has_decision_value(payload: dict[str, Any]) -> bool:
    if any(_mode_value(payload.get(field)) for field in _MODE_FIELDS):
        return True
    return _workflow_flag(payload) is not None


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
        raise ValueError("router decision must be an object")
    return payload


def _clean_reason(value: Any) -> str:
    reason = re.sub(r"\s+", " ", str(value or "")).strip()
    return reason[:_MAX_REASON_CHARS] or "需要多阶段任务编排"


def _decision_mode(payload: dict[str, Any]) -> str:
    for field in _MODE_FIELDS:
        if mode := _mode_value(payload.get(field)):
            return mode
    workflow_flag = _workflow_flag(payload)
    if workflow_flag is not None:
        return "dynamic_workflow" if workflow_flag else "direct"
    return ""


def _mode_value(value: Any) -> str:
    if isinstance(value, dict):
        for field in _MODE_VALUE_FIELDS:
            if mode := _mode_value(value.get(field)):
                return mode
        return ""
    text = _normalize_mode_text(value)
    if text in _VALID_MODES:
        return text
    for mode, aliases in _MODE_ALIASES.items():
        if text in aliases:
            return mode
    return ""


def _normalize_mode_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return text.replace("-", "_")


def _workflow_flag(payload: dict[str, Any]) -> bool | None:
    for field in _WORKFLOW_FLAG_FIELDS:
        if field in payload:
            return _coerce_bool(payload.get(field))
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "需要", "是"}:
        return True
    if text in {"0", "false", "no", "n", "不需要", "否"}:
        return False
    return None


def _decision_confidence(payload: dict[str, Any]) -> float:
    for key in ("confidence", "score", "probability", "prob"):
        confidence = _parse_confidence(payload.get(key))
        if confidence is not None:
            return confidence
    return 0.0


def _parse_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        multiplier = 0.01 if text.endswith("%") else 1.0
        value = text.rstrip("%").strip()
    else:
        multiplier = 1.0
    try:
        confidence = float(value) * multiplier
    except (TypeError, ValueError):
        return None
    if confidence > 1.0:
        confidence /= 100.0
    return round(max(0.0, min(confidence, 1.0)), 4)


def _should_use_workflow(decision: dict[str, Any] | None) -> bool:
    if not decision:
        return False
    return decision["mode"] == "dynamic_workflow"
