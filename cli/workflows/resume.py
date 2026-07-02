"""Resume prompt builder for persisted workflow runs."""

from __future__ import annotations

import re
from typing import Any

from utils.tool_result_preview import tool_result_brief_lines

_SHORT_CONTINUATION_REPLIES = {
    "继续",
    "继续吧",
    "继续做",
    "接着",
    "接着做",
    "接着来",
    "刚才那个继续",
    "继续刚才那个",
    "接着刚才那个",
    "上个继续",
    "上一个继续",
    "继续上个",
    "继续上一个",
}
_RECENT_CONTEXT_MARKERS = (
    "刚才",
    "上面",
    "前面",
    "上个",
    "上一个",
    "其中",
    "候选",
    "推荐",
    "入选",
    "名单",
    "前者",
    "后者",
)
_RECENT_CONTEXT_PRONOUNS = ("这个", "那个", "这只", "那只", "它", "他们", "它们")
_RECENT_CONTEXT_QUESTIONS = (
    "哪个更",
    "哪只更",
    "哪个最",
    "哪只最",
    "第一个",
    "第二个",
    "第三个",
)
_RECENT_CONTEXT_ACTIONS = ("怎么", "看", "风险", "稳", "买", "卖", "加", "减", "为什么", "原因")
_RECENT_CONTEXT_TOPIC_EXCLUSIONS = ("cli", "工具", "项目", "系统", "代码")
_HANDOFF_TOOL_ORDER = (
    ("last_screen_result", "screen_stocks"),
    ("last_recommendation_event_eval", "evaluate_recommendation_events"),
    ("last_ai_report", "generate_ai_report"),
    ("last_strategy_decision", "generate_strategy_decision"),
)
_HANDOFF_BY_TOOL = {item[1]: item for item in _HANDOFF_TOOL_ORDER}
_HANDOFF_BY_TOOL["recommendation_event_eval"] = ("last_recommendation_event_eval", "evaluate_recommendation_events")


def build_resume_prompt(run: dict[str, Any]) -> str:
    """Build a user-visible continuation prompt from a stored workflow run."""

    plan = run.get("plan") if isinstance(run.get("plan"), dict) else {}
    lines = [
        f"继续 workflow {run.get('run_id', '')}",
        f"类型: {run.get('label', '')} / 状态: {run.get('status', '')}",
        f"原始问题: {run.get('user_text', '')}",
    ]
    if tools := _join_items(plan.get("allowed_tools")):
        lines.append(f"可用工具: {tools}")
    if summary := _clip_text(run.get("result_summary"), 500):
        lines.append(f"已有结果摘要: {summary}")
    lines.extend(["", "已记录步骤:"])
    for idx, step in enumerate(_step_dicts(plan), start=1):
        lines.extend(_step_lines(idx, step))
    if evidence := _workflow_event_evidence_lines(run.get("events"), limit=6):
        lines.extend(["", "已记录关键证据:"])
        lines.extend(f"- {line}" for line in evidence)
    lines.extend(
        [
            "",
            "请基于以上 workflow 状态继续推进；不要重复已完成工具调用，优先处理 failed/pending/skipped 的步骤。",
            "保持原有 tool_scope 和 depends_on，只有用户新要求或已有事实推翻时才调整。",
        ]
    )
    return "\n".join(lines)


def is_recent_workflow_followup(user_text: str) -> bool:
    """Return True when a short chat reply likely means continuing the last workflow."""

    text = _one_line(user_text).lower()
    if not text or "workflow" in text or "工作流" in text or re.search(r"\bwf_[a-z0-9_-]+\b", text):
        return False
    compact = re.sub(r"[\s。！!,.，、？?]+", "", text)
    if compact in _SHORT_CONTINUATION_REPLIES:
        return True
    if len(compact) > 12:
        return False
    has_previous_ref = any(token in compact for token in ("刚才", "上个", "上一个", "前面"))
    has_continue = "继续" in compact or "接着" in compact
    return has_previous_ref and has_continue


def should_include_recent_workflow_context(user_text: str) -> bool:
    """Return True when a user turn appears to reference the latest workflow output."""

    text = _one_line(user_text).lower()
    if not text or text.startswith("继续 workflow") or re.search(r"\bwf_[a-z0-9_-]+\b", text):
        return False
    compact = re.sub(r"[\s。！!,.，、？?]+", "", text)
    if any(marker in compact for marker in _RECENT_CONTEXT_MARKERS):
        return True
    if any(marker in compact for marker in _RECENT_CONTEXT_QUESTIONS):
        return True
    if any(topic in compact for topic in _RECENT_CONTEXT_TOPIC_EXCLUSIONS):
        return False
    if len(compact) <= 18 and any(marker in compact for marker in _RECENT_CONTEXT_PRONOUNS):
        return any(action in compact for action in _RECENT_CONTEXT_ACTIONS)
    return bool(
        re.search(
            r"(?:第[一二三四五六七八九十\d]+个?|[一二三四五六七八九十\d]+号).{0,8}(?:怎么|看|风险|稳|买|卖)", compact
        )
    )


def build_chat_resume_prompt(run: dict[str, Any], user_text: str) -> str:
    prompt = build_resume_prompt(run)
    if reply := _one_line(user_text):
        return f"{prompt}\n\n用户当前回复: {reply}"
    return prompt


def build_recent_workflow_context(run: dict[str, Any]) -> str:
    """Build bounded context for natural follow-ups to the latest workflow result."""

    run_id = _one_line(run.get("run_id"))
    if not run_id:
        return ""
    plan = run.get("plan") if isinstance(run.get("plan"), dict) else {}
    lines = [
        "<recent-workflow-context>",
        "以下是当前 TUI 会话最近一次 workflow，仅当用户问题引用刚才、上面、候选、推荐、序号或代词时参考；否则忽略。",
        f"run_id: {run_id}",
        f"类型: {_one_line(run.get('label')) or _one_line(plan.get('label'))}",
        f"状态: {_one_line(run.get('status'))}",
        f"原始问题: {_clip_text(run.get('user_text'), 220)}",
    ]
    if summary := _clip_text(run.get("result_summary"), 420):
        lines.append(f"结果摘要: {summary}")
    for idx, step in enumerate(_step_dicts(plan)[:5], start=1):
        if line := _context_step_line(idx, step):
            lines.append(line)
    for line in _workflow_event_evidence_lines(run.get("events"), limit=6):
        lines.append(f"证据: {line}")
    lines.append("</recent-workflow-context>")
    return "\n".join(line for line in lines if line.strip())


def _step_dicts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in plan.get("steps", []) if isinstance(step, dict)]


def _step_lines(idx: int, step: dict[str, Any]) -> list[str]:
    status = _one_line(step.get("status")) or "pending"
    title = _one_line(step.get("title")) or "task"
    line = f"{idx}. [{status}] {title}"
    if meta := _step_meta(step):
        line = f"{line} ({meta})"
    if summary := _clip_text(step.get("summary"), 500):
        line = f"{line} - {summary}"
    lines = [line]
    if prompt := _clip_text(step.get("prompt"), 360):
        lines.append(f"   prompt: {prompt}")
    if context := _clip_text(step.get("context"), 260):
        lines.append(f"   context: {context}")
    return lines


def _step_meta(step: dict[str, Any]) -> str:
    parts: list[str] = []
    if step_id := _one_line(step.get("step_id")):
        parts.append(f"id={step_id}")
    if phase := _one_line(step.get("phase")):
        parts.append(f"phase={phase}")
    if deps := _join_items(step.get("depends_on")):
        parts.append(f"depends_on={deps}")
    scope = _join_items(step.get("tool_scope") or step.get("tools"))
    effective = _join_items(step.get("effective_tool_scope"))
    if scope:
        parts.append(f"tool_scope={scope}")
    if effective and effective != scope:
        parts.append(f"effective_tools={effective}")
    return "; ".join(parts)


def _context_step_line(idx: int, step: dict[str, Any]) -> str:
    title = _one_line(step.get("title")) or "task"
    status = _one_line(step.get("status")) or "pending"
    parts = [f"{idx}. [{status}] {title}"]
    if scope := _join_items(step.get("tool_scope") or step.get("effective_tool_scope") or step.get("tools")):
        parts.append(f"tools={scope}")
    if summary := _clip_text(step.get("summary"), 260):
        parts.append(f"summary={summary}")
    return " | ".join(parts)


def _workflow_event_evidence_lines(events: Any, *, limit: int) -> list[str]:
    rows: list[str] = []
    for payload in reversed(_event_payloads(events)):
        step = payload.get("step") if isinstance(payload.get("step"), dict) else {}
        for line in (*_event_evidence_items(step.get("evidence")), *_event_handoff_lines(payload)):
            _append_evidence_line(rows, line, limit=limit)
            if len(rows) >= limit:
                return rows
    return rows


def _event_payloads(events: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in events if isinstance(events, list) else []:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _event_handoff_lines(payload: dict[str, Any]) -> tuple[str, ...]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    detail = source.get("agent_detail") if isinstance(source.get("agent_detail"), dict) else {}
    handoff = detail.get("handoff_state") if isinstance(detail.get("handoff_state"), dict) else {}
    tool_calls = [str(item) for item in detail.get("tool_calls", []) if str(item)]
    return tuple(
        line for key, tool in _handoff_tool_order(tool_calls) for line in _tool_brief_lines(handoff, key, tool)
    )


def _tool_brief_lines(handoff: dict[str, Any], key: str, tool_name: str) -> list[str]:
    result = handoff.get(key)
    return tool_result_brief_lines(tool_name, result, max_lines=2) if isinstance(result, dict) else []


def _handoff_tool_order(tool_calls: list[str]) -> list[tuple[str, str]]:
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tool_name in tool_calls:
        if item := _HANDOFF_BY_TOOL.get(tool_name):
            _append_handoff_tool(ordered, seen, item)
    for item in _HANDOFF_TOOL_ORDER:
        _append_handoff_tool(ordered, seen, item)
    return ordered


def _append_handoff_tool(ordered: list[tuple[str, str]], seen: set[str], item: tuple[str, str]) -> None:
    if item[0] not in seen:
        seen.add(item[0])
        ordered.append(item)


def _event_evidence_items(value: Any) -> tuple[str, ...]:
    if isinstance(value, list | tuple):
        return tuple(text for item in value if (text := _one_line(item)))
    return (text,) if (text := _one_line(value)) else ()


def _append_evidence_line(rows: list[str], value: Any, *, limit: int) -> None:
    text = _clip_text(value, 240)
    if len(rows) < limit and text and text not in rows:
        rows.append(text)


def _join_items(value: Any) -> str:
    return ", ".join(_iter_items(value))


def _iter_items(value: Any) -> tuple[str, ...]:
    if isinstance(value, list | tuple):
        items = value
    elif value is None:
        return ()
    else:
        items = str(value).split(",")
    return tuple(text for item in items if (text := _one_line(item)))


def _clip_text(value: Any, limit: int) -> str:
    text = _one_line(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())
