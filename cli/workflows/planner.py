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

MAX_WORKFLOW_STEPS = 24
ASK_USER_TOOL = "ask_user_question"
TASK_LIST_FIELDS = ("tasks", "steps", "items", "subtasks", "jobs", "actions", "plan")
PHASE_LIST_FIELDS = ("phases", "stages", "stage_groups", "sections", "groups", "milestones")
SCRIPT_CONTAINER_FIELDS = ("workflow", "workflow_script", "script", "plan")
PROMPT_FIELDS = ("prompt", "instruction", "instructions", "task", "description", "goal", "objective")
TOOL_SCOPE_FIELDS = (
    "tool_scope",
    "allowed_tools",
    "required_tools",
    "required_tool",
    "tool_names",
    "tool_name",
    "tools",
    "tool",
    "functions",
    "function",
    "function_calls",
    "function_call",
    "tool_calls",
    "tool_call",
    "tool_uses",
    "tool_use",
    "calls",
    "call",
)
TOOL_SCOPE_NESTED_FIELDS = (
    "tool_scope",
    "allowed",
    "required",
    "names",
    *TOOL_SCOPE_FIELDS,
)

_PLAN_SYSTEM_PROMPT = """\
你是 Wyckoff CLI 的动态 workflow 编排器。

根据用户输入生成一个可执行 workflow script。script 是任务计划，不是解释文本，只能是 JSON。
自然语言语义、上下文恢复和任务拆分由你完成；runtime 只负责工具边界、并发、持久化和安全控制。

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
          "tools": ["本 task 必须/允许使用的精确工具名；需要真实数据、分析或决策且工具摘要里有对应工具时必须填写"],
          "depends_on": ["可选，必须先完成的 task id"],
          "prompt": "完整任务说明",
          "context": "可选上下文",
          "rationale": "可选，为什么需要这一步",
          "success_criteria": "可选，这一步完成的判定标准",
          "risk_guard": "可选，这一步不能越过的边界"
        }
      ]
    }
  ],
  "synthesis_prompt": "最终汇总时应该如何整合结果"
}

运行边界:
- 只输出 JSON，不要 Markdown，不要代码块。
- phases 总任务数 1-24 个；如果要处理很多股票或对象，用工具批量处理，不要为每个对象单独生成 task。
- 同一 phase 内无依赖的 task 会并发执行；depends_on 指向的已命名 task 会先完成。
- 如果用 depends_on/after/needs/dependencies 表达 task 依赖，runtime 会跨 phase 按依赖顺序切批执行。
- 不需要选择内部执行角色；不要填写 agent/role。
- 工具是脚本契约：能用工具验证或交付的 task，必须用工具摘要里的精确工具名填写 tools；只有纯汇总/解释且不需要工具时才省略。
- 不要生成“识别代码/读取事实/形成计划”这类无工具占位 task；如果工具能完成，直接把对应工具写进同一个 task。
- 如果 task 需要候选、研报或持仓事实，填写 depends_on 指向提供这些事实的 task id，不要让它们无依赖并发。
- 选股交付如果要求候选、理由、风险边界或攻防计划，脚本里必须出现 screen_stocks，并在需要攻防/买卖计划/风险边界时出现 generate_strategy_decision；需要研报时再使用 generate_ai_report。
- 任务拆分围绕用户当前目标；能单步完成就生成 1 个 task，需要事实收集/分析/决策链路时再拆分。
- 每个 task 尽量写清 rationale / success_criteria / risk_guard，让执行 agent 知道目标、验收和边界。
- 能用工具验证的事实交给 task 验证；只有执行对象仍不明确，或会产生写入、交易、高风险动作时才澄清。
- 能合理推断的表述偏差、口语省略或术语混用，按最高置信假设生成可执行 task，并让最终回答说明假设。
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
    payload = _unwrap_script_container(deepcopy(script))
    runtime = payload.setdefault("runtime", {})
    if source_run_id:
        runtime["rerun_of"] = source_run_id
    if workflow_args not in (None, ""):
        runtime["args"] = workflow_args
    if only_step_id:
        runtime["only_step_id"] = only_step_id
    runtime["planner"] = "stored_script"
    return payload


def _mark_model_script(script: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(script)
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    runtime.setdefault("planner", "model_script")
    payload["runtime"] = runtime
    return payload


def _limit_generated_script(script: dict[str, Any]) -> dict[str, Any]:
    phases = _script_phases(script)
    total = sum(len(_phase_tasks(phase)) for phase in phases)
    if total <= MAX_WORKFLOW_STEPS:
        return script
    payload = {key: value for key, value in script.items() if key not in (*TASK_LIST_FIELDS, "phases")}
    payload["phases"] = _limited_phases(phases)
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    runtime.update(
        {
            "step_limit": MAX_WORKFLOW_STEPS,
            "original_step_count": total,
            "truncated_step_count": total - MAX_WORKFLOW_STEPS,
        }
    )
    payload["runtime"] = runtime
    return payload


def _limited_phases(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = 0
    limited: list[dict[str, Any]] = []
    for phase in phases:
        if kept >= MAX_WORKFLOW_STEPS:
            break
        tasks = _phase_tasks(phase)
        keep = tasks[: MAX_WORKFLOW_STEPS - kept]
        if keep:
            limited.append(_phase_with_tasks(phase, keep))
            kept += len(keep)
    return limited


def _phase_with_tasks(phase: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {key: value for key, value in phase.items() if key not in TASK_LIST_FIELDS}
    payload["tasks"] = tasks
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
        script = _normalize_generated_script(_loads_script(text))
    except Exception as exc:
        return _fallback_script(user_text, context, reason=f"planner failed: {exc}")
    if not isinstance(script, dict):
        return _fallback_script(user_text, context, reason="planner returned non-object JSON")
    return _mark_model_script(_limit_generated_script(script))


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
        if match:
            return json.loads(match.group(0))
        if script := _outline_script(raw):
            return script
        raise


def _normalize_generated_script(script: Any) -> Any:
    if isinstance(script, dict):
        return _unwrap_script_container(script)
    if isinstance(script, list):
        return _lightweight_script(_safe_task_list(script), "planner returned top-level task list") or script
    if isinstance(script, str):
        return _outline_script(script) or script
    return script


def _unwrap_script_container(script: dict[str, Any]) -> dict[str, Any]:
    for field in SCRIPT_CONTAINER_FIELDS:
        nested = script.get(field)
        if isinstance(nested, dict) and _workflow_script_like(nested):
            return _script_with_container_defaults(script, nested)
    return script


def _script_with_container_defaults(container: dict[str, Any], nested: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(nested)
    for field in ("title", "rationale", "synthesis_prompt", "runtime"):
        if field in container and payload.get(field) in (None, "", [], {}):
            payload[field] = deepcopy(container[field])
    return payload


def _workflow_script_like(value: dict[str, Any]) -> bool:
    return bool(_first_phase_list(value) or _first_task_list(value) or _generated_task_like(value))


def _outline_script(text: str) -> dict[str, Any] | None:
    tasks = _text_task_items(text)
    return _lightweight_script(tasks, "planner returned outline text")


def _lightweight_script(tasks: list[dict[str, Any]], reason: str) -> dict[str, Any] | None:
    if not tasks:
        return None
    return {
        "title": "动态任务",
        "rationale": reason,
        "phases": [{"id": "outline", "title": "任务清单", "tasks": tasks}],
        "synthesis_prompt": "基于任务结果给出简洁中文答复。",
    }


def _strip_json_fence(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _script_steps(script: dict[str, Any], user_text: str, context: WorkflowContext) -> list[WorkflowStep]:
    steps: list[WorkflowStep] = []
    args_text = _runtime_args(script)
    infer_text_tools = _should_infer_text_tools(script)
    allowed_tool_names = _context_tool_names(context) if infer_text_tools else None
    for phase in _script_phases(script):
        steps.extend(_phase_steps(phase, user_text, args_text, infer_text_tools, allowed_tool_names))
        if len(steps) >= MAX_WORKFLOW_STEPS:
            break
    steps = _normalize_step_dependencies(steps)
    steps = _stabilize_tool_dependencies(steps)
    steps = _filter_runtime_steps(steps, script)
    if steps:
        return steps[:MAX_WORKFLOW_STEPS]
    fallback = _fallback_script(user_text, context, reason="planner returned no valid tasks")
    return _script_steps(fallback, user_text, context)


def _phase_steps(
    phase: dict[str, Any],
    user_text: str,
    args_text: str,
    infer_text_tools: bool,
    allowed_tool_names: set[str] | None,
) -> list[WorkflowStep]:
    phase_id = _slug(phase.get("id") or phase.get("title") or "phase")
    steps: list[WorkflowStep] = []
    for task in _phase_tasks(phase):
        step = _task_step(task, phase_id, user_text, args_text, infer_text_tools, allowed_tool_names)
        if step:
            steps.append(step)
    return steps


def _task_step(
    task: dict[str, Any],
    phase_id: str,
    user_text: str,
    args_text: str,
    infer_text_tools: bool,
    allowed_tool_names: set[str] | None,
) -> WorkflowStep | None:
    if not _generated_task_like(task):
        return None
    title = str(task.get("title") or task.get("name") or task.get("id") or "task").strip()
    prompt = _task_prompt(task, title, user_text)
    prompt = _render_runtime_args(prompt, args_text)
    context = _render_runtime_args(str(task.get("context") or "").strip(), args_text)
    step_id = _slug(task.get("id") or title)
    return WorkflowStep(
        step_id=step_id,
        title=title[:80],
        tools=(),
        agent="task",
        prompt=prompt,
        context=context,
        rationale=_task_meta(task, ("rationale", "reason", "why")),
        success_criteria=_task_meta(task, ("success_criteria", "done_when", "acceptance_criteria", "expected_output")),
        risk_guard=_task_meta(task, ("risk_guard", "guard", "guardrail", "guardrails", "boundary", "constraints")),
        phase=phase_id,
        depends_on=_task_dependencies(task),
        tool_scope=_task_tool_scope(task, title, prompt, context, infer_text_tools, allowed_tool_names),
        dynamic=True,
    )


def _script_phases(script: dict[str, Any]) -> list[dict[str, Any]]:
    phases = _first_phase_list(script)
    if phases:
        return phases
    tasks = _first_task_list(script)
    if tasks:
        return [{"id": "top_level", "title": script.get("title") or "动态任务", "tasks": tasks}]
    if _generated_task_like(script):
        return [{"id": "top_level", "title": script.get("title") or "动态任务", "tasks": [script]}]
    return []


def _first_phase_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for field in PHASE_LIST_FIELDS:
        phases = _safe_list(payload.get(field))
        if phases:
            return phases
    return []


def _phase_tasks(phase: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = _first_task_list(phase)
    if tasks:
        return tasks
    return [phase] if _generated_task_like(phase) else []


def _first_task_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for field in TASK_LIST_FIELDS:
        items = _safe_task_list(payload.get(field))
        if items:
            return items
    return []


def _task_tool_scope(
    task: dict[str, Any],
    title: str = "",
    prompt: str = "",
    context: str = "",
    infer_text_tools: bool = False,
    allowed_tool_names: set[str] | None = None,
) -> tuple[str, ...]:
    names: list[str] = []
    for field in TOOL_SCOPE_FIELDS:
        for item in _tool_scope_items(task.get(field)):
            if name := _tool_name(item):
                names.append(name)
    explicit = tuple(dict.fromkeys(names))
    if explicit:
        return _filter_tool_scope(explicit, allowed_tool_names)
    if not infer_text_tools:
        return ()
    return _filter_tool_scope(_text_task_tool_scope(" ".join((title, prompt, context))), allowed_tool_names)


def _should_infer_text_tools(script: dict[str, Any]) -> bool:
    runtime = script.get("runtime")
    planner = runtime.get("planner") if isinstance(runtime, dict) else ""
    return planner in {"model_script", "fallback_script"}


def _context_tool_names(context: WorkflowContext) -> set[str]:
    return {name for name in context.allowed_tools if name and not name.startswith("delegate_to_")}


def _filter_tool_scope(scope: tuple[str, ...], allowed_tool_names: set[str] | None) -> tuple[str, ...]:
    scope = _drop_question_tool_when_fact_tool_present(scope)
    if allowed_tool_names is None:
        return scope
    return tuple(name for name in scope if name in allowed_tool_names)


def _drop_question_tool_when_fact_tool_present(scope: tuple[str, ...]) -> tuple[str, ...]:
    concrete = [name for name in scope if name and name != ASK_USER_TOOL]
    if not concrete:
        return scope
    return tuple(name for name in scope if name != ASK_USER_TOOL)


def _tool_name(raw: Any) -> str:
    if isinstance(raw, dict):
        raw = _tool_name_payload_value(raw)
    raw_text = str(raw or "")
    key = _normalize_tool_key(raw_text)
    key = _TOOL_NAME_ALIASES.get(key, key)
    if key.startswith("delegate_to_"):
        return ""
    if key in TOOL_SPECS:
        return key
    return _embedded_tool_name(raw_text)


def _tool_name_payload_value(payload: dict[str, Any]) -> Any:
    for field in ("function", "tool"):
        nested = payload.get(field)
        if isinstance(nested, dict):
            return _tool_name_payload_value(nested)
    return (
        payload.get("name")
        or payload.get("tool")
        or payload.get("id")
        or payload.get("display_name")
        or payload.get("label")
    )


def _embedded_tool_name(raw: str) -> str:
    text = raw.lower()
    for name, spec in TOOL_SPECS.items():
        if name in text or str(spec.display_name or "") in raw:
            return "" if name.startswith("delegate_to_") else name
    return ""


def _normalize_tool_key(raw: Any) -> str:
    key = re.sub(r"[\s/-]+", "_", str(raw or "").strip().lower()).strip("_")
    key = re.sub(r"(_?tool|工具)$", "", key).strip("_")
    return key


def _tool_name_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for name, spec in TOOL_SPECS.items():
        for value in (name, spec.display_name):
            key = _normalize_tool_key(value)
            if key:
                aliases[key] = name
    return aliases


_TOOL_NAME_ALIASES = _tool_name_aliases()

_TEXT_TASK_TOOL_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "screen_stocks",
        (
            "screen_stocks",
            "全市场扫描",
            "扫描",
            "扫描候选",
            "候选扫描",
            "扫描股票",
            "筛选",
            "筛选候选",
            "筛股",
            "选股",
            "候选股",
            "候选股票",
            "股票池",
            "好股票",
            "好票",
            "好标的",
            "优质标的",
            "机会池",
        ),
    ),
    (
        "analyze_stock",
        (
            "analyze_stock",
            "个股诊断",
            "单股诊断",
            "读盘诊断",
            "量价结构",
            "个股结构",
        ),
    ),
    (
        "generate_ai_report",
        (
            "generate_ai_report",
            "深度审讯",
            "ai研报",
            "ai 研报",
            "生成研报",
            "研报",
        ),
    ),
    (
        "generate_strategy_decision",
        (
            "generate_strategy_decision",
            "攻防",
            "买卖计划",
            "风险边界",
            "交易计划",
            "策略决策",
            "触发位",
            "失效位",
            "止损位",
            "入场位",
            "出场位",
            "去留",
            "持仓去留",
            "风险动作",
            "操作动作",
            "处理动作",
            "操作建议",
            "调仓",
            "减仓",
            "加仓",
            "仓位动作",
        ),
    ),
    ("portfolio", ("portfolio", "持仓", "仓位", "组合", "磁场")),
    ("run_backtest", ("run_backtest", "回测")),
    ("get_market_overview", ("get_market_overview", "大盘水温", "市场环境", "市场风险")),
)


def _generated_task_like(task: dict[str, Any]) -> bool:
    fields = ("id", "title", "name", *PROMPT_FIELDS, *TOOL_SCOPE_FIELDS)
    return any(str(task.get(field) or "").strip() for field in fields)


def _task_prompt(task: dict[str, Any], title: str, user_text: str) -> str:
    for field in PROMPT_FIELDS:
        value = str(task.get(field) or "").strip()
        if value:
            return value
    return title or user_text


def _task_meta(task: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        if value := _task_meta_value(task.get(field)):
            return value
    return ""


def _task_meta_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (list, tuple, set)):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return "；".join(f"{key}: {item}" for key, item in value.items() if str(item).strip())
    return str(value).strip()


def _task_dependencies(task: dict[str, Any]) -> tuple[str, ...]:
    deps: list[str] = []
    for field in ("depends_on", "dependsOn", "dependencies", "after", "needs", "requires"):
        deps.extend(dep for item in _field_items(task.get(field)) if (dep := _dependency_id(item)))
    return tuple(dict.fromkeys(dep for dep in deps if dep))


def _normalize_step_dependencies(steps: list[WorkflowStep]) -> list[WorkflowStep]:
    aliases = _dependency_aliases(steps)
    for step in steps:
        deps: list[str] = []
        for dep in step.depends_on:
            resolved = aliases.get(dep, dep)
            if resolved and resolved != step.step_id and resolved not in deps:
                deps.append(resolved)
        step.depends_on = tuple(deps)
    return steps


def _dependency_aliases(steps: list[WorkflowStep]) -> dict[str, str]:
    buckets: dict[str, set[str]] = {}
    for step in steps:
        for alias in (step.step_id, _slug(step.title)):
            if alias:
                buckets.setdefault(alias, set()).add(step.step_id)
    return {alias: next(iter(ids)) for alias, ids in buckets.items() if len(ids) == 1}


def _stabilize_tool_dependencies(steps: list[WorkflowStep]) -> list[WorkflowStep]:
    for step in steps:
        step.depends_on = _stabilized_step_dependencies(step, steps)
    return steps


def _stabilized_step_dependencies(step: WorkflowStep, steps: list[WorkflowStep]) -> tuple[str, ...]:
    scope = set(step.tool_scope)
    deps = list(step.depends_on)
    if "generate_ai_report" in scope and "screen_stocks" not in scope:
        _append_dependency(deps, _nearest_tool_step_id(step, steps, "screen_stocks"))
    if "generate_strategy_decision" in scope and not scope.intersection({"screen_stocks", "generate_ai_report"}):
        _append_dependency(
            deps,
            _nearest_tool_step_id(step, steps, "generate_ai_report")
            or _nearest_tool_step_id(step, steps, "screen_stocks"),
        )
    if "generate_strategy_decision" in scope and not scope.intersection({"portfolio", "get_market_overview"}):
        _append_dependency(
            deps,
            _nearest_tool_step_id(step, steps, "portfolio")
            or _nearest_tool_step_id(step, steps, "get_market_overview"),
        )
    return tuple(deps)


def _nearest_tool_step_id(step: WorkflowStep, steps: list[WorkflowStep], tool_name: str) -> str:
    rows = [candidate for candidate in steps if _same_phase(step, candidate) and candidate is not step]
    return _nearest_step_id(step, steps, rows, tool_name) or _nearest_step_id(
        step,
        steps,
        [candidate for candidate in steps if candidate is not step],
        tool_name,
    )


def _nearest_step_id(
    step: WorkflowStep,
    steps: list[WorkflowStep],
    rows: list[WorkflowStep],
    tool_name: str,
) -> str:
    previous = [
        candidate for candidate in rows if tool_name in candidate.tool_scope and _step_before(candidate, step, steps)
    ]
    following = [
        candidate for candidate in rows if tool_name in candidate.tool_scope and _step_before(step, candidate, steps)
    ]
    candidate = (previous[-1:] or following[:1] or [None])[0]
    return candidate.step_id if candidate else ""


def _same_phase(left: WorkflowStep, right: WorkflowStep) -> bool:
    return (left.phase or "") == (right.phase or "")


def _step_before(left: WorkflowStep, right: WorkflowStep, steps: list[WorkflowStep]) -> bool:
    return steps.index(left) < steps.index(right)


def _append_dependency(deps: list[str], dep: str) -> None:
    if dep and dep not in deps:
        deps.append(dep)


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


def _tool_scope_items(value: Any) -> list[Any]:
    items: list[Any] = []
    for item in _field_items(value):
        nested = _nested_tool_scope_items(item)
        items.extend(nested or [item])
    return items


def _nested_tool_scope_items(value: Any) -> list[Any]:
    if not isinstance(value, dict):
        return []
    items: list[Any] = []
    for field in TOOL_SCOPE_NESTED_FIELDS:
        items.extend(_field_items(value.get(field)))
    return items


def _safe_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [_keyed_payload(key, item) for key, item in value.items() if isinstance(item, dict)]
    return []


def _safe_task_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return _text_task_items(value)
    if isinstance(value, list):
        return [payload for index, item in enumerate(value, 1) if (payload := _task_payload(item, index))]
    if isinstance(value, dict):
        return [payload for key, item in value.items() if (payload := _keyed_task_payload(key, item))]
    return []


def _text_task_items(text: str) -> list[dict[str, Any]]:
    lines = [_strip_list_marker(line) for line in str(text or "").splitlines()]
    items = [line for line in lines if line]
    if not items and text.strip():
        items = [text.strip()]
    return [_string_task_payload(item, index) for index, item in enumerate(items, 1)]


def _task_payload(item: Any, index: int) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if isinstance(item, str):
        return _string_task_payload(item, index)
    return {}


def _keyed_task_payload(key: Any, item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return _keyed_payload(key, item)
    key_text = str(key or "").strip()
    if isinstance(item, str):
        payload = _string_task_payload(item, key_text or 1)
        if key_text:
            payload["id"] = key_text
        return payload
    return {}


def _string_task_payload(text: str, key: Any) -> dict[str, Any]:
    title = _strip_list_marker(text)
    if not title:
        return {}
    payload = {"id": str(key), "title": title, "prompt": title}
    if tools := _text_task_tool_scope(title):
        payload["tools"] = list(tools)
    return payload


def _text_task_tool_scope(text: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    names = [name for name, markers in _TEXT_TASK_TOOL_MARKERS if any(marker in normalized for marker in markers)]
    return tuple(dict.fromkeys(names))


def _strip_list_marker(text: str) -> str:
    return re.sub(r"^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*", "", text).strip()


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
    title = _fallback_task_title(user_text, context)
    return {
        "title": title,
        "rationale": reason,
        "runtime": {"planner": "fallback_script", "fallback_reason": reason},
        "phases": [
            {
                "id": "single_pass",
                "title": "动态单步执行",
                "tasks": [
                    {
                        "id": "agent_task",
                        "title": title,
                        "prompt": _fallback_task_prompt(user_text),
                    }
                ],
            }
        ],
        "synthesis_prompt": "基于任务结果给出简洁中文答复。",
    }


def _fallback_task_prompt(user_text: str) -> str:
    return (
        "直接处理用户请求。按上下文理解自然语言语义，并用可用工具读取或验证事实；"
        "只有工具无法恢复关键参数或涉及写入、交易、高风险确认时，才向用户澄清。\n\n"
        f"用户原文：{user_text}"
    )


def _fallback_task_title(user_text: str, context: WorkflowContext) -> str:
    text = re.sub(r"\s+", " ", user_text).strip(" \n\t。.")
    if not text:
        return context.label or "处理当前请求"
    return text[:40]
