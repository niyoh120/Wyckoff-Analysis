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
TASK_LIST_FIELDS = ("tasks", "steps", "items", "subtasks", "jobs", "actions")
PROMPT_FIELDS = ("prompt", "instruction", "instructions", "task", "description", "goal", "objective")
TOOL_SCOPE_FIELDS = ("tool_scope", "allowed_tools", "tools", "tool")

WORKFLOW_TOOL_AGENTS = {
    "search_stock_by_name": "analysis",
    "analyze_stock": "analysis",
    "generate_ai_report": "analysis",
    "portfolio": "trading",
    "generate_strategy_decision": "trading",
    "update_portfolio": "trading",
    "screen_stocks": "research",
    "run_backtest": "research",
    "check_background_tasks": "research",
    "get_market_overview": "research",
    "get_market_history": "research",
    "query_history": "research",
    "web_fetch": "research",
    "read_file": "research",
}

WORKFLOW_AGENT_ALIASES = {
    "research": "research",
    "researcher": "research",
    "delegate_to_research": "research",
    "data": "research",
    "market": "research",
    "scan": "research",
    "backtest": "research",
    "研究": "research",
    "调研": "research",
    "数据": "research",
    "扫描": "research",
    "回测": "research",
    "analysis": "analysis",
    "analyst": "analysis",
    "delegate_to_analysis": "analysis",
    "diagnosis": "analysis",
    "diagnose": "analysis",
    "structure": "analysis",
    "分析": "analysis",
    "诊断": "analysis",
    "结构": "analysis",
    "复盘": "analysis",
    "trading": "trading",
    "trader": "trading",
    "trade": "trading",
    "delegate_to_trading": "trading",
    "decision": "trading",
    "risk": "trading",
    "action": "trading",
    "交易": "trading",
    "决策": "trading",
    "风控": "trading",
    "攻防": "trading",
    "动作": "trading",
}

_PLAN_SYSTEM_PROMPT = """\
你是 Wyckoff CLI 的动态 workflow 编排器。

根据用户输入生成一个可执行 workflow script。script 不是解释文本，只能是 JSON。
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
          "agent": "可选，research|analysis|trading",
          "tools": ["可选，本 task 需要的工具名"],
          "depends_on": ["可选，必须先完成的 task id"],
          "prompt": "给该 sub-agent 的完整任务说明",
          "context": "可选，传给该 agent 的上下文"
        }
      ]
    }
  ],
  "synthesis_prompt": "最终汇总时应该如何整合各 agent 结果"
}

运行边界:
- 只输出 JSON，不要 Markdown，不要代码块。
- phases 总任务数 1-1000 个。
- 同一 phase 内的 task 会并发执行；有依赖关系的 task 必须拆到后续 phase。
- 如果用 depends_on/after/needs/dependencies 表达 task 依赖，runtime 会按依赖顺序切批执行。
- 如果任务已经通过 tool/标题/prompt 表达清楚，agent 字段可以省略，runtime 会按工具或上下文选择执行 agent。
- 任务拆分围绕用户当前目标；能单步完成就生成 1 个 task，需要事实收集/分析/决策链路时再拆分。
- 按用户最可能的任务意图恢复上下文，不要把表达形式本身当作额外 task 或澄清理由。
- 能用工具验证的事实交给 sub-agent 验证；不要因为可搜索或可读取的信息先问用户。
- 只有执行对象仍不明确，或会产生写入、交易、高风险动作时才澄清。
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
    for phase in _script_phases(script, context):
        steps.extend(_phase_steps(phase, user_text, args_text, context))
        if len(steps) >= MAX_WORKFLOW_STEPS:
            break
    steps = _filter_runtime_steps(steps, script)
    if steps:
        return steps[:MAX_WORKFLOW_STEPS]
    fallback = _fallback_script(user_text, context, reason="planner returned no valid tasks")
    return _script_steps(fallback, user_text, context)


def _phase_steps(
    phase: dict[str, Any],
    user_text: str,
    args_text: str,
    context: WorkflowContext,
) -> list[WorkflowStep]:
    phase_id = _slug(phase.get("id") or phase.get("title") or "phase")
    steps: list[WorkflowStep] = []
    for task in _phase_tasks(phase, context):
        step = _task_step(task, phase_id, user_text, args_text, context)
        if step:
            steps.append(step)
    return steps


def _task_step(
    task: dict[str, Any],
    phase_id: str,
    user_text: str,
    args_text: str,
    context: WorkflowContext,
) -> WorkflowStep | None:
    agent = _task_agent(task, context)
    if not agent:
        return None
    title = str(task.get("title") or task.get("name") or task.get("id") or f"{agent} task").strip()
    prompt = _task_prompt(task, title, user_text)
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
        depends_on=_task_dependencies(task),
        tool_scope=_task_tool_scope(task),
        dynamic=True,
    )


def _script_phases(script: dict[str, Any], context: WorkflowContext) -> list[dict[str, Any]]:
    phases = _safe_list(script.get("phases"))
    if phases:
        return phases
    tasks = _first_task_list(script)
    if tasks:
        return [{"id": "top_level", "title": script.get("title") or "动态任务", "tasks": tasks}]
    if _task_agent(script, context):
        return [{"id": "top_level", "title": script.get("title") or "动态任务", "tasks": [script]}]
    return []


def _phase_tasks(phase: dict[str, Any], context: WorkflowContext) -> list[dict[str, Any]]:
    tasks = _first_task_list(phase)
    if tasks:
        return tasks
    return [phase] if _task_agent(phase, context) else []


def _first_task_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for field in TASK_LIST_FIELDS:
        items = _safe_list(payload.get(field))
        if items:
            return items
    return []


def _task_agent(task: dict[str, Any], context: WorkflowContext) -> str:
    candidates: list[Any] = [task.get("agent"), task.get("role"), task.get("assignee"), task.get("tool")]
    tools = task.get("tools")
    candidates.extend(tools if isinstance(tools, (list, tuple)) else [tools])
    for raw in candidates:
        agent = _normalize_workflow_agent(raw)
        if agent:
            return agent
        agent = _tool_agent(raw)
        if agent:
            return agent
    return _fallback_agent(context)


def _normalize_workflow_agent(raw: Any) -> str:
    key = re.sub(r"[\s/-]+", "_", str(raw or "").strip().lower()).strip("_")
    key = re.sub(r"_agent$", "", key)
    agent = WORKFLOW_AGENT_ALIASES.get(key, "")
    return agent if agent in ALLOWED_WORKFLOW_AGENTS else ""


def _tool_agent(raw: Any) -> str:
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("tool") or raw.get("id")
    key = re.sub(r"[\s/-]+", "_", str(raw or "").strip().lower()).strip("_")
    return WORKFLOW_TOOL_AGENTS.get(key, "")


def _task_tool_scope(task: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for field in TOOL_SCOPE_FIELDS:
        value = task.get(field)
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if name := _tool_name(item):
                names.append(name)
    return tuple(dict.fromkeys(names))


def _tool_name(raw: Any) -> str:
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("tool") or raw.get("id")
    key = re.sub(r"[\s/-]+", "_", str(raw or "").strip().lower()).strip("_")
    if key.startswith("delegate_to_"):
        return ""
    return key if key in TOOL_SPECS else ""


def _task_prompt(task: dict[str, Any], title: str, user_text: str) -> str:
    for field in PROMPT_FIELDS:
        value = str(task.get(field) or "").strip()
        if value:
            return value
    return title or user_text


def _task_dependencies(task: dict[str, Any]) -> tuple[str, ...]:
    deps: list[str] = []
    for field in ("depends_on", "dependsOn", "dependencies", "after", "needs", "requires"):
        value = task.get(field)
        items = value if isinstance(value, (list, tuple)) else [value]
        deps.extend(dep for item in items if (dep := _dependency_id(item)))
    return tuple(dict.fromkeys(dep for dep in deps if dep))


def _dependency_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id") or value.get("task_id") or value.get("step_id") or value.get("title")
    text = str(value or "").strip()
    return _slug(text) if text else ""


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
                        "prompt": _fallback_task_prompt(user_text),
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


def _fallback_task_prompt(user_text: str) -> str:
    return (
        "直接处理用户请求。按上下文理解自然语言，并用可用工具读取或验证事实；"
        "只有工具无法恢复关键参数或涉及写入、交易、高风险确认时，才向用户澄清。\n\n"
        f"用户原文：{user_text}"
    )
