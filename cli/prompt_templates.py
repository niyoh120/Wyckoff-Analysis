"""Reusable prompt templates for recurring research workflows."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(os.path.expanduser("~/.wyckoff/prompts"))

_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    description: str
    prompt: str
    argument_hint: str = ""


BUILTIN_PROMPT_TEMPLATES: dict[str, PromptTemplate] = {
    "daily": PromptTemplate(
        name="daily",
        description="每日盘面复盘：大盘水温、机会池、持仓风险",
        argument_hint="[关注方向/持仓]",
        prompt=(
            "做一次每日 Wyckoff 投研复盘。\n"
            "用户补充：{user_input}\n\n"
            "请按这个顺序执行：\n"
            "1. 调用 get_market_overview() 判断大盘水温。\n"
            '2. 调用 query_history(source="recommendation", limit=20) 查看近期形态复盘池。\n'
            '3. 调用 query_history(source="signal", status="pending", limit=20) 查看待确认信号。\n'
            '4. 调用 query_history(source="attribution", limit=1) 查看策略治理器、升降权建议、latest_source/remote_error、latest_operator_summary、next_action、promotion_status、promotion_checklist、latest_execution_state(active_scope/生效标志) 和 latest_operations。\n'
            '5. 如果用户提到持仓或当前组合，再调用 portfolio(mode="view")；没有提到就不要主动诊断持仓。\n'
            "6. 输出：市场状态、今日可观察方向、归因数据来源、归因运营摘要、shadow 最新新增/移除样本、归因调权当前影响范围、dynamic 是否只适合继续 shadow、需要回避的风险、下一步动作。"
        ),
    ),
    "review-l4": PromptTemplate(
        name="review-l4",
        description="复核 L4/AI 子集：解释全量正式 L4 与 Step3 入选差异",
        argument_hint="[日期/股票/疑问]",
        prompt=(
            "复核最近一次漏斗 L4 输出与 Step3 AI 入选情况。\n"
            "用户补充：{user_input}\n\n"
            "重点回答：\n"
            "1. 全量正式 L4 有哪些，不要只看进入 AI 的子集。\n"
            "2. 哪些进入 Step3，为什么数量可能少于正式 L4。\n"
            "3. 如果输出看起来不全，先区分是展示层截断、飞书分段，还是 pipeline 实际缺失。\n"
            "4. 给出能验证的日志、文件或命令线索。"
        ),
    ),
    "holding-risk": PromptTemplate(
        name="holding-risk",
        description="持仓风险体检：只在用户需要时做诊断",
        argument_hint="[风险偏好/重点股票]",
        prompt=(
            "做一次持仓风险体检。\n"
            "用户补充：{user_input}\n\n"
            "请按这个顺序执行：\n"
            '1. 调用 portfolio(mode="diagnose") 获取持仓诊断。\n'
            "2. 调用 get_market_overview() 获取大盘环境。\n"
            "3. 将每只持仓分成 EXIT/TRIM/HOLD/PROBE/ATTACK 或观察。\n"
            "4. 输出时保留证据：阶段、触发信号、风险位、需要等待的确认条件。"
        ),
    ),
    "step3-audit": PromptTemplate(
        name="step3-audit",
        description="Step3 研报输入审计：检查候选、上下文 cap、模型与预览文件",
        argument_hint="[运行日期/模型/异常]",
        prompt=(
            "审计 Step3 批量研报输入。\n"
            "用户补充：{user_input}\n\n"
            "请重点检查：\n"
            "1. Step3 实际输入候选数量、分轨数量和上下文 cap。\n"
            "2. 使用的模型、fallback 模型，以及是否产生输入预览文件。\n"
            "3. 如果用户怀疑没输出全，先确认 logs/step3_llm_input_preview.md 或相关 artifact 是否完整。\n"
            "4. 最终用产品语言说明用户在飞书/日志里应该看到什么。"
        ),
    ),
    "feishu-summary": PromptTemplate(
        name="feishu-summary",
        description="飞书通知复盘：检查发送、分段、预览和降级路径",
        argument_hint="[workflow/run id/消息现象]",
        prompt=(
            "复盘一次飞书通知链路。\n"
            "用户补充：{user_input}\n\n"
            "请按这个顺序判断：\n"
            "1. 先确认 pipeline 实际产物是否完整。\n"
            "2. 再确认飞书发送方式：文件预览、长卡片、分段消息或 webhook。\n"
            "3. 如果看起来被截断，区分展示限制和实际发送失败。\n"
            "4. 输出：用户应查看的位置、可能原因、最小修复建议。"
        ),
    ),
}


def _parse_prompt_md(path: Path) -> PromptTemplate | None:
    """Parse ~/.wyckoff/prompts/<name>.md with optional YAML frontmatter."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if not text.startswith("---"):
        name = path.stem.strip().lower()
        if not _VALID_NAME_RE.match(name):
            return None
        return PromptTemplate(name=name, description="", prompt=text.strip())

    parts = text.split("---", 2)
    if len(parts) < 3:
        name = path.stem.strip().lower()
        if not _VALID_NAME_RE.match(name):
            return None
        return PromptTemplate(name=name, description="", prompt=text.strip())

    import yaml

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}

    name = str(meta.get("name", path.stem)).strip().lower()
    if not _VALID_NAME_RE.match(name):
        return None
    return PromptTemplate(
        name=name,
        description=str(meta.get("description", "") or ""),
        argument_hint=str(meta.get("argument_hint", meta.get("argument-hint", "")) or ""),
        prompt=parts[2].strip(),
    )


def load_user_prompt_templates() -> dict[str, PromptTemplate]:
    """Load user prompt templates from ~/.wyckoff/prompts/."""

    templates: dict[str, PromptTemplate] = {}
    if not PROMPTS_DIR.is_dir():
        return templates
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        template = _parse_prompt_md(path)
        if template:
            templates[template.name] = template
    return templates


def load_prompt_templates() -> dict[str, PromptTemplate]:
    """Merge built-in and user prompt templates; user templates override built-ins."""

    merged = dict(BUILTIN_PROMPT_TEMPLATES)
    merged.update(load_user_prompt_templates())
    return merged


def render_prompt_template(template: PromptTemplate, user_input: str = "") -> str:
    """Render a prompt template with the user's free-form argument text."""

    rendered = template.prompt.replace("{user_input}", user_input.strip())
    rendered = rendered.replace("$ARGUMENTS", user_input.strip())
    return rendered.strip()
