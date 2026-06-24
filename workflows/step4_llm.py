"""Step4 LLM decision service."""

from __future__ import annotations

import logging
from collections.abc import Callable

from core.prompts import PRIVATE_PM_DECISION_JSON_PROMPT
from integrations.llm_client import call_llm
from tools.debug_io import dump_model_input
from workflows.step4_decision_parser import parse_decisions
from workflows.step4_models import Step4DecisionResult, Step4InputContext, Step4RunOptions

logger = logging.getLogger(__name__)


def call_step4_decision_model(
    options: Step4RunOptions,
    context: Step4InputContext,
    report_progress: Callable[[str, str, float], None],
) -> tuple[bool, str, Step4DecisionResult | None]:
    dump_model_input(
        step_prefix="step4",
        model=f"{options.provider}:{options.model}",
        system_prompt=PRIVATE_PM_DECISION_JSON_PROMPT,
        user_message=context.user_message,
        symbols=sorted(context.allowed_codes),
    )
    report_progress("LLM决策", "计算中", 0.5)
    try:
        raw = call_llm(
            provider=options.provider,
            model=options.model,
            api_key=options.api_key,
            system_prompt=PRIVATE_PM_DECISION_JSON_PROMPT,
            user_message=context.user_message,
            base_url=options.llm_base_url or None,
            timeout=300,
            max_output_tokens=options.runtime_config.max_output_tokens,
        )
    except Exception as e:
        logger.error("模型调用失败: %s", e, exc_info=True)
        return False, "llm_failed", None

    market_view, decisions, parse_err = parse_decisions(raw, context.allowed_codes, context.name_map)
    if parse_err:
        logger.error("决策 JSON 解析失败: %s", parse_err)
        return False, "llm_failed", None
    if not decisions:
        logger.info("模型未产出有效决策，跳过")
        return True, "skipped_no_decisions", None
    return True, "ok", Step4DecisionResult(market_view=market_view, decisions=decisions)
