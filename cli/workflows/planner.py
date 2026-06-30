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

ALLOWED_WORKFLOW_AGENTS = {"task", "research", "analysis", "trading"}
MAX_WORKFLOW_STEPS = 1000
TASK_LIST_FIELDS = ("tasks", "steps", "items", "subtasks", "jobs", "actions")
PROMPT_FIELDS = ("prompt", "instruction", "instructions", "task", "description", "goal", "objective")
TOOL_SCOPE_FIELDS = ("tool_scope", "allowed_tools", "tools", "tool")

TOOL_ALIASES = {
    "查持仓": "portfolio",
    "持仓数据": "portfolio",
    "查看持仓": "portfolio",
    "股票搜索": "search_stock_by_name",
    "搜索代码": "search_stock_by_name",
    "市场概览": "get_market_overview",
    "市场水温": "get_market_overview",
    "行情回看": "get_market_history",
    "历史行情": "get_market_history",
    "选股": "screen_stocks",
    "股票筛选": "screen_stocks",
    "筛选股票": "screen_stocks",
    "扫描股票": "screen_stocks",
    "ai研报": "generate_ai_report",
    "深度研报": "generate_ai_report",
    "策略决策": "generate_strategy_decision",
    "问用户": "ask_user_question",
    "提问": "ask_user_question",
    "询问用户": "ask_user_question",
    "后台任务": "check_background_tasks",
    "任务状态": "check_background_tasks",
}

WORKFLOW_AGENT_ALIASES = {
    "task": "task",
    "workflow_task": "task",
    "dynamic_task": "task",
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

根据用户输入生成一个可执行 workflow script。script 是任务计划，不是解释文本，只能是 JSON。
自然语言理解、上下文恢复和任务拆分由你完成；runtime 只负责工具边界、并发、持久化和安全控制。

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
          "tools": ["可选，本 task 允许使用的具体工具名；不写则 runtime 按上下文提供工具"],
          "depends_on": ["可选，必须先完成的 task id"],
          "prompt": "完整任务说明",
          "context": "可选上下文"
        }
      ]
    }
  ],
  "synthesis_prompt": "最终汇总时应该如何整合结果"
}

运行边界:
- 只输出 JSON，不要 Markdown，不要代码块。
- phases 总任务数 1-1000 个。
- 同一 phase 内的 task 会并发执行；有依赖关系的 task 必须拆到后续 phase。
- 如果用 depends_on/after/needs/dependencies 表达 task 依赖，runtime 会按依赖顺序切批执行。
- 不需要选择内部执行角色；不要填写 agent/role，历史脚本带有这些字段时 runtime 才兼容处理。
- 如果某个 task 只应看部分工具，用 tools 限定具体工具；不要用工具名表达自然语言意图。
- 任务拆分围绕用户当前目标；能单步完成就生成 1 个 task，需要事实收集/分析/决策链路时再拆分。
- 按用户最可能的任务意图恢复上下文，不要把表达形式本身当作额外 task 或澄清理由。
- 用户输入有错字、口语化或省略时，按最可能意图继续；不要生成“确认错字/改写问题”的 task。
- 能用工具验证的事实交给 task 验证；不要因为可搜索或可读取的信息先问用户。
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
        f"当前可用工具摘要（供你决定任务边界，不要直接调用）:\n{catalog}\n\n"
        "请生成 workflow JSON。"
    )


def _tool_catalog(tools: Any | None, context: WorkflowContext) -> str:
    allowed = _planner_visible_tools(context.allowed_tools or tuple(TOOL_SPECS))
    try:
        names = [schema["name"] for schema in tools.schemas(allowed)][:24] if tools else sorted(allowed)[:24]
    except Exception:
        names = sorted(allowed)[:24]
    return "\n".join(
        f"- {name}: {TOOL_SPECS.get(name).display_name if TOOL_SPECS.get(name) else name}" for name in names
    )


def _planner_visible_tools(names: tuple[str, ...]) -> set[str]:
    return {name for name in names if name and not name.startswith("delegate_to_")}


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
        tools=_agent_delegate_tools(agent),
        agent=agent,
        prompt=prompt,
        context=context,
        phase=phase_id,
        depends_on=_task_dependencies(task),
        tool_scope=_task_tool_scope(task),
        dynamic=True,
    )


def _agent_delegate_tools(agent: str) -> tuple[str, ...]:
    return () if agent == "task" else (f"delegate_to_{agent}",)


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
    if _task_tool_scope(task):
        return "task"
    for raw in (task.get("agent"), task.get("role"), task.get("assignee")):
        agent = _normalize_workflow_agent(raw)
        if agent:
            return agent
    return _fallback_agent(context, _task_fallback_text(task))


def _normalize_workflow_agent(raw: Any) -> str:
    key = re.sub(r"[\s/-]+", "_", str(raw or "").strip().lower()).strip("_")
    key = re.sub(r"_agent$", "", key)
    agent = WORKFLOW_AGENT_ALIASES.get(key, "")
    return agent if agent in ALLOWED_WORKFLOW_AGENTS else ""


def _task_tool_scope(task: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for field in TOOL_SCOPE_FIELDS:
        for item in _field_items(task.get(field)):
            if name := _tool_name(item):
                names.append(name)
    return tuple(dict.fromkeys(names))


def _tool_name(raw: Any) -> str:
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("tool") or raw.get("id") or raw.get("display_name") or raw.get("label")
    key = _normalize_tool_key(raw)
    if key.startswith("delegate_to_"):
        return ""
    return key if key in TOOL_SPECS else _tool_aliases().get(key, "")


def _normalize_tool_key(raw: Any) -> str:
    key = re.sub(r"[\s/-]+", "_", str(raw or "").strip().lower()).strip("_")
    key = re.sub(r"(_?tool|工具)$", "", key).strip("_")
    return key


def _tool_aliases() -> dict[str, str]:
    aliases = {_normalize_tool_key(spec.display_name): name for name, spec in TOOL_SPECS.items()}
    aliases.update({_normalize_tool_key(alias): name for alias, name in TOOL_ALIASES.items()})
    return aliases


def _task_fallback_text(task: dict[str, Any]) -> str:
    parts = [str(task.get(field) or "") for field in ("title", "name", "id", *PROMPT_FIELDS)]
    return "\n".join(part for part in parts if part.strip())


def _task_prompt(task: dict[str, Any], title: str, user_text: str) -> str:
    for field in PROMPT_FIELDS:
        value = str(task.get(field) or "").strip()
        if value:
            return value
    return title or user_text


def _task_dependencies(task: dict[str, Any]) -> tuple[str, ...]:
    deps: list[str] = []
    for field in ("depends_on", "dependsOn", "dependencies", "after", "needs", "requires"):
        deps.extend(dep for item in _field_items(task.get(field)) if (dep := _dependency_id(item)))
    return tuple(dict.fromkeys(dep for dep in deps if dep))


def _dependency_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id") or value.get("task_id") or value.get("step_id") or value.get("title")
    text = str(value or "").strip()
    return _slug(text) if text else ""


def _field_items(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        return [part for part in re.split(r"[,，、\n]+", value) if part.strip()]
    return [value]


def _safe_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [_keyed_payload(key, item) for key, item in value.items() if isinstance(item, dict)]
    return []


def _keyed_payload(key: Any, item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    key_text = str(key or "").strip()
    if key_text:
        payload.setdefault("id", key_text)
        payload.setdefault("title", key_text)
    return payload


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
    agent = _fallback_agent(context, user_text)
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


def _fallback_agent(_context: WorkflowContext, _text: str = "") -> str:
    return "task"


def _fallback_task_prompt(user_text: str) -> str:
    return (
        "直接处理用户请求。按上下文理解自然语言，并用可用工具读取或验证事实；"
        "只有工具无法恢复关键参数或涉及写入、交易、高风险确认时，才向用户澄清。\n\n"
        f"用户原文：{user_text}"
    )
