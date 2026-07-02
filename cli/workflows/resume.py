"""Resume prompt builder for persisted workflow runs."""

from __future__ import annotations

from typing import Any


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
    lines.extend(
        [
            "",
            "请基于以上 workflow 状态继续推进；不要重复已完成工具调用，优先处理 failed/pending/skipped 的步骤。",
            "保持原有 tool_scope 和 depends_on，只有用户新要求或已有事实推翻时才调整。",
        ]
    )
    return "\n".join(lines)


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
