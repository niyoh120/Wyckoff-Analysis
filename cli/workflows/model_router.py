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

MIN_WORKFLOW_CONFIDENCE = 0.67
_MAX_REASON_CHARS = 120
_MODE_FIELDS = ("mode", "route", "decision", "type")
_CONFIDENCE_FIELDS = ("confidence", "score", "probability", "置信度")
_WORKFLOW_FLAG_FIELDS = ("workflow", "use_workflow", "dynamic_workflow")
_DIRECT_ALIASES = {
    "chat",
    "direct",
    "direct_agent",
    "general",
    "general_chat",
    "normal",
    "普通",
    "普通对话",
    "直接",
    "直接回答",
    "直答",
    "自由对话",
}
_WORKFLOW_ALIASES = {
    "dynamic",
    "dynamic_task",
    "dynamic_workflow",
    "multi_agent",
    "multi_step",
    "plan",
    "task",
    "task_workflow",
    "workflow",
    "分阶段",
    "动态",
    "动态workflow",
    "动态任务",
    "动态工作流",
    "动态编排",
    "编排",
}

_ROUTER_SYSTEM_PROMPT = """\
你是 Wyckoff CLI 的 turn router。用户只会在 agent 内聊天，不会输入专门命令。

只判断这一轮应该直接交给普通 agent，还是启动动态 workflow 编排。

direct:
- 闲聊、概念解释、单个事实查询。
- 查看持仓、单只股票诊断、提交一次回测、一次普通工具调用就能完成的请求。

dynamic_workflow:
- 用户要完整成果：选股、复盘、研究、攻防计划、去留动作、风险预案。
- 需要先收集事实，再分析结构，最后综合成交易/观察动作。
- 需要多个视角或多个 sub-agent 并行/分阶段处理。

要求:
- 按用户最可能的任务意图判断，不要把表达形式当作澄清理由。
- 不要按关键词机械判断。
- 不确定时选 direct。
- 只输出 JSON，不要 Markdown。

JSON schema:
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
    if decision["mode"] == "dynamic_workflow":
        return f"模型动态 workflow 置信度不足，直接处理：{decision['reason']}"
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
        mode = _normalize_mode(payload.get(field))
        if mode:
            return mode
    for field in _WORKFLOW_FLAG_FIELDS:
        mode = _workflow_flag_mode(payload.get(field))
        if mode:
            return mode
    return ""


def _normalize_mode(value: Any) -> str:
    key = _normalize_mode_key(value)
    if key in _DIRECT_ALIASES:
        return "direct"
    if key in _WORKFLOW_ALIASES:
        return "dynamic_workflow"
    return ""


def _normalize_mode_key(value: Any) -> str:
    key = re.sub(r"[\s/-]+", "_", str(value or "").strip().lower()).strip("_")
    return key.replace("工作流", "workflow")


def _workflow_flag_mode(value: Any) -> str:
    if isinstance(value, bool):
        return "dynamic_workflow" if value else "direct"
    key = _normalize_mode_key(value)
    if key in {"1", "true", "yes", "y", "需要", "是"}:
        return "dynamic_workflow"
    if key in {"0", "false", "no", "n", "不需要", "否"}:
        return "direct"
    return _normalize_mode(value)


def _decision_confidence(payload: dict[str, Any]) -> float:
    for field in _CONFIDENCE_FIELDS:
        confidence = _parse_confidence(payload.get(field))
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
    return max(0.0, min(confidence, 1.0))


def _should_use_workflow(decision: dict[str, Any] | None) -> bool:
    if not decision:
        return False
    return decision["mode"] == "dynamic_workflow" and decision["confidence"] >= MIN_WORKFLOW_CONFIDENCE
