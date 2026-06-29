"""Model-authored workflow script planner."""

from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from typing import Any

from cli.tools import TOOL_SPECS
from cli.workflows.models import WorkflowContext, WorkflowRun, WorkflowStep
from cli.workflows.router import route_workflow

ALLOWED_WORKFLOW_AGENTS = {"research", "analysis", "trading"}
MAX_WORKFLOW_STEPS = 1000

_PLAN_SYSTEM_PROMPT = """\
你是 Wyckoff CLI 的动态 workflow 编排器。

你必须根据用户输入生成一个可执行 workflow script。script 不是解释文本，只能是 JSON。
runtime 会按 JSON 调度 sub-agent；你不能假设 script 可以直接读文件、写文件、跑 shell 或访问网络。

可用 agent:
- research: 数据收集、市场水温、历史记录、扫描、回测任务提交
- analysis: 个股/持仓结构诊断、研报分析、量价解释
- trading: 去留决策、攻防计划、风险动作

输出 JSON schema:
{
  "title": "简短中文标题",
  "rationale": "为什么这样拆分",
  "phases": [
    {
      "id": "phase_id",
      "title": "阶段标题",
      "tasks": [
        {
          "id": "task_id",
          "title": "任务标题",
          "agent": "research|analysis|trading",
          "prompt": "给该 sub-agent 的完整任务说明",
          "context": "可选，传给该 agent 的上下文"
        }
      ]
    }
  ],
  "synthesis_prompt": "最终汇总时应该如何整合各 agent 结果"
}

约束:
- 只输出 JSON，不要 Markdown，不要代码块。
- phases 总任务数 1-1000 个。
- 同一 phase 内的 task 会并发执行；有依赖关系的 task 必须拆到后续 phase。
- 普通单轮工具型请求不要拆成模板化多阶段；1 个能直接执行的 task 更好。
- 用户可能有错别字、简称或口语省略；先按上下文推断最可能含义，并在 task prompt 里要求 sub-agent 用工具验证。
- 如果可用工具能读取或推断信息，task prompt 必须要求 sub-agent 先调用工具探测，例如 portfolio 读取持仓、search_stock_by_name 识别股票、analyze_stock 诊断个股、get_market_overview 读取市场。
- 只有可用工具也无法获得的必需参数才允许澄清；不要为了更完整而先问用户。
- 缺少不可替代的关键参数时，生成一个 task 说明如何澄清；不要把可由模型理解或工具验证的信息交回给用户。
- 不要生成会写入持仓、交易或文件的任务。
"""


def plan_workflow(
    user_text: str,
    *,
    session_id: str = "",
    context: WorkflowContext | None = None,
    provider: Any | None = None,
    tools: Any | None = None,
    workflow_script: dict[str, Any] | None = None,
    source_run_id: str = "",
    workflow_args: Any = None,
    only_step_id: str = "",
) -> WorkflowRun:
    """Create a model-authored workflow run for one user turn."""

    context = context or route_workflow(user_text)
    raw_script = (
        _normalize_supplied_script(workflow_script, source_run_id, workflow_args, only_step_id)
        if workflow_script
        else _generate_script(user_text, context, provider, tools)
    )
    steps = _script_steps(raw_script, user_text, context)
    return WorkflowRun(
        run_id=f"wf_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        user_text=user_text,
        context=context,
        steps=steps,
        script=raw_script,
    )


def _normalize_supplied_script(
    script: dict[str, Any],
    source_run_id: str,
    workflow_args: Any,
    only_step_id: str,
) -> dict[str, Any]:
    payload = deepcopy(script)
    runtime = payload.setdefault("runtime", {})
    if source_run_id:
        runtime["rerun_of"] = source_run_id
    if workflow_args not in (None, ""):
        runtime["args"] = workflow_args
    if only_step_id:
        runtime["only_step_id"] = only_step_id
    runtime["planner"] = "stored_script"
    return payload


def _generate_script(
    user_text: str,
    context: WorkflowContext,
    provider: Any | None,
    tools: Any | None,
) -> dict[str, Any]:
    if provider is None:
        return _fallback_script(user_text, context, reason="provider unavailable")
    prompt = _planner_user_prompt(user_text, context, tools)
    try:
        text = _collect_planner_text(provider, prompt)
        script = _loads_script(text)
    except Exception as exc:
        return _fallback_script(user_text, context, reason=f"planner failed: {exc}")
    if not isinstance(script, dict):
        return _fallback_script(user_text, context, reason="planner returned non-object JSON")
    return script


def _planner_user_prompt(user_text: str, context: WorkflowContext, tools: Any | None) -> str:
    catalog = _tool_catalog(tools, context)
    return (
        f"用户请求:\n{user_text}\n\n"
        f"运行上下文: {context.label} ({context.name})\n"
        f"路由原因: {context.route_reason or '-'}\n\n"
        f"当前可用工具摘要（供你决定 agent 任务边界，不要直接调用）:\n{catalog}\n\n"
        "请生成 workflow JSON。"
    )


def _tool_catalog(tools: Any | None, context: WorkflowContext) -> str:
    allowed = set(context.allowed_tools or TOOL_SPECS)
    try:
        names = [schema["name"] for schema in tools.schemas(allowed)][:24] if tools else sorted(allowed)[:24]
    except Exception:
        names = sorted(allowed)[:24]
    return "\n".join(
        f"- {name}: {TOOL_SPECS.get(name).display_name if TOOL_SPECS.get(name) else name}" for name in names
    )


def _collect_planner_text(provider: Any, prompt: str) -> str:
    chunks: list[str] = []
    messages = [{"role": "user", "content": prompt}]
    for chunk in provider.chat_stream(messages, [], _PLAN_SYSTEM_PROMPT):
        if chunk.get("type") == "text_delta":
            chunks.append(str(chunk.get("text", "")))
    return "".join(chunks).strip()


def _loads_script(text: str) -> Any:
    raw = _strip_json_fence(text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _strip_json_fence(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _script_steps(script: dict[str, Any], user_text: str, context: WorkflowContext) -> list[WorkflowStep]:
    steps: list[WorkflowStep] = []
    args_text = _runtime_args(script)
    for phase in _safe_list(script.get("phases")):
        steps.extend(_phase_steps(phase, user_text, args_text))
        if len(steps) >= MAX_WORKFLOW_STEPS:
            break
    steps = _filter_runtime_steps(steps, script)
    if steps:
        return steps[:MAX_WORKFLOW_STEPS]
    fallback = _fallback_script(user_text, context, reason="planner returned no valid tasks")
    return _script_steps(fallback, user_text, context)


def _phase_steps(phase: dict[str, Any], user_text: str, args_text: str) -> list[WorkflowStep]:
    phase_id = _slug(phase.get("id") or phase.get("title") or "phase")
    steps: list[WorkflowStep] = []
    for task in _safe_list(phase.get("tasks")):
        step = _task_step(task, phase_id, user_text, args_text)
        if step:
            steps.append(step)
    return steps


def _task_step(task: dict[str, Any], phase_id: str, user_text: str, args_text: str) -> WorkflowStep | None:
    agent = str(task.get("agent", "")).strip().lower()
    if agent not in ALLOWED_WORKFLOW_AGENTS:
        return None
    title = str(task.get("title") or task.get("id") or f"{agent} task").strip()
    prompt = str(task.get("prompt") or title or user_text).strip()
    prompt = _render_runtime_args(prompt, args_text)
    context = _render_runtime_args(str(task.get("context") or "").strip(), args_text)
    step_id = _slug(task.get("id") or title)
    return WorkflowStep(
        step_id=step_id,
        title=title[:80],
        tools=(f"delegate_to_{agent}",),
        agent=agent,
        prompt=prompt,
        context=context,
        phase=phase_id,
        dynamic=True,
    )


def _safe_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _runtime_args(script: dict[str, Any]) -> str:
    runtime = script.get("runtime", {})
    if not isinstance(runtime, dict):
        return ""
    args = runtime.get("args", "")
    return json.dumps(args, ensure_ascii=False, default=str) if isinstance(args, (dict, list)) else str(args or "")


def _render_runtime_args(prompt: str, args_text: str) -> str:
    if not args_text:
        return prompt
    if "{args}" in prompt:
        return prompt.replace("{args}", args_text)
    return f"{prompt}\n\n本次运行输入:\n{args_text}"


def _filter_runtime_steps(steps: list[WorkflowStep], script: dict[str, Any]) -> list[WorkflowStep]:
    runtime = script.get("runtime", {})
    if not isinstance(runtime, dict):
        return steps
    only_step_id = str(runtime.get("only_step_id", "") or "")
    if not only_step_id:
        return steps
    return [step for step in steps if step.step_id == only_step_id]


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff-]+", "_", str(value or "task")).strip("_")
    return text[:40] or "task"


def _fallback_script(user_text: str, context: WorkflowContext, *, reason: str) -> dict[str, Any]:
    agent = _fallback_agent(context)
    return {
        "title": context.label,
        "rationale": reason,
        "phases": [
            {
                "id": "single_pass",
                "title": "动态单步执行",
                "tasks": [
                    {
                        "id": "agent_task",
                        "title": "让 sub-agent 处理用户请求",
                        "agent": agent,
                        "prompt": user_text,
                    }
                ],
            }
        ],
        "synthesis_prompt": "基于 sub-agent 结果给出简洁中文答复。",
    }


def _fallback_agent(context: WorkflowContext) -> str:
    if context.name in {"stock_screen", "backtest"}:
        return "research"
    if context.name == "portfolio_review":
        return "trading"
    return "analysis"
