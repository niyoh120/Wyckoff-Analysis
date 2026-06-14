"""Resume prompt builder for persisted workflow runs."""

from __future__ import annotations

from typing import Any


def build_resume_prompt(run: dict[str, Any]) -> str:
    """Build a user-visible continuation prompt from a stored workflow run."""

    lines = [
        f"继续 workflow {run.get('run_id', '')}",
        f"类型: {run.get('label', '')} / 状态: {run.get('status', '')}",
        f"原始问题: {run.get('user_text', '')}",
        "",
        "已记录步骤:",
    ]
    for idx, step in enumerate(run.get("plan", {}).get("steps", []), start=1):
        lines.append(f"{idx}. [{step.get('status', '')}] {step.get('title', '')} {step.get('summary', '')}")
    lines.extend(
        [
            "",
            "请基于以上 workflow 状态继续推进；不要重复已完成工具调用，优先处理 failed/pending/skipped 的步骤。",
        ]
    )
    return "\n".join(lines)
