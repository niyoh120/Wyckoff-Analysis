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
_MODE_FIELDS = ("mode", "route", "runtime", "execution_mode")
_DYNAMIC_MODE_ALIASES = {
    "dynamic",
    "dynamic workflow",
    "dynamicworkflow",
    "dynamic_workflow",
    "workflow",
    "workflow_executor",
    "workflowexecutor",
    "动态",
    "动态workflow",
    "动态工作流",
    "工作流",
}
_DIRECT_MODE_ALIASES = {
    "agent",
    "chat",
    "direct",
    "directagent",
    "direct_agent",
    "general_chat",
    "generalchat",
    "normal",
    "普通",
    "普通agent",
    "直接",
    "直接agent",
    "直接回答",
    "直接处理",
}
_WORKFLOW_FLAG_FIELDS = ("workflow", "use_workflow", "dynamic_workflow", "needs_workflow")

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
    decision, fallback_reason = _model_decision(user_text, provider)
    if decision:
        return _context_from_model_decision(decision)
    return _context_with_router_fallback(route_workflow(user_text), fallback_reason)


def _context_from_model_decision(decision: dict[str, Any]) -> WorkflowContext:
    return replace(
        WORKFLOWS["dynamic_task"] if _should_use_workflow(decision) else WORKFLOWS["general_chat"],
        route_reason=_model_route_reason(decision),
        route_confidence=float(decision["confidence"]),
        route_matches=("model_router",),
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
    mode = _decision_mode(payload)
    if not mode:
        return None
    confidence = _decision_confidence(payload)
    return {
        "mode": mode,
        "confidence": confidence,
        "reason": _clean_reason(payload.get("reason")),
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
        raise ValueError("router decision must be an object")
    return payload


def _clean_reason(value: Any) -> str:
    reason = re.sub(r"\s+", " ", str(value or "")).strip()
    return reason[:_MAX_REASON_CHARS] or "需要多阶段任务编排"


def _decision_mode(payload: dict[str, Any]) -> str:
    for field in _MODE_FIELDS:
        if mode := _mode_alias(payload.get(field)):
            return mode
    workflow_flag = _workflow_flag(payload)
    if workflow_flag is not None:
        return "dynamic_workflow" if workflow_flag else "direct"
    return ""


def _mode_alias(value: Any) -> str:
    text = _normalize_mode_text(value)
    if not text:
        return ""
    if text in _VALID_MODES or text in _DIRECT_MODE_ALIASES:
        return "direct" if text in _DIRECT_MODE_ALIASES else text
    if text in _DYNAMIC_MODE_ALIASES:
        return "dynamic_workflow"
    return ""


def _normalize_mode_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return text.replace("-", "_").replace(" ", "")


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
