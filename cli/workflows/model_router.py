"""Model-assisted workflow routing for natural-language turns."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from typing import Any

from cli.workflows.models import WorkflowContext
from cli.workflows.router import WORKFLOWS, route_workflow

logger = logging.getLogger(__name__)

MIN_WORKFLOW_CONFIDENCE = 0.67
_MAX_REASON_CHARS = 120

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
- 理解真实意图，不要按关键词机械判断。
- 口语、近义表达或轻微误写，按最合理的任务意图判断。
- 不确定时选 direct。
- 只输出 JSON，不要 Markdown。

JSON schema:
{"mode":"direct|dynamic_workflow","confidence":0.0,"reason":"简短中文原因"}
"""


def route_workflow_with_model(user_text: str, provider: Any | None) -> WorkflowContext:
    """Use the model to decide dynamic workflow routing when deterministic routing is general."""

    base = route_workflow(user_text)
    if not base.is_general:
        return base
    decision = _model_decision(user_text, provider)
    if not _should_use_workflow(decision):
        return base
    return replace(
        WORKFLOWS["dynamic_task"],
        route_reason=f"模型判断需要动态 workflow：{decision['reason']}",
        route_confidence=float(decision["confidence"]),
        route_matches=("model_router",),
    )


def _model_decision(user_text: str, provider: Any | None) -> dict[str, Any] | None:
    if provider is None or not hasattr(provider, "chat"):
        return None
    try:
        response = provider.chat(
            [{"role": "user", "content": f"用户请求:\n{user_text}\n\n请输出 routing JSON。"}],
            [],
            _ROUTER_SYSTEM_PROMPT,
        )
        return _parse_decision(response)
    except Exception:
        logger.debug("model workflow router failed", exc_info=True)
        return None


def _parse_decision(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict) or response.get("type") == "tool_calls":
        return None
    try:
        payload = _loads_json(str(response.get("text") or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    mode = str(payload.get("mode", "")).strip().lower()
    if mode not in {"direct", "dynamic_workflow"}:
        return None
    try:
        confidence = float(payload.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "mode": mode,
        "confidence": max(0.0, min(confidence, 1.0)),
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


def _should_use_workflow(decision: dict[str, Any] | None) -> bool:
    if not decision:
        return False
    return decision["mode"] == "dynamic_workflow" and decision["confidence"] >= MIN_WORKFLOW_CONFIDENCE
