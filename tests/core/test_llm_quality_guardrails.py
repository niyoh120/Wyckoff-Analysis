from cli.sub_agent_prompts import ANALYSIS_AGENT_PROMPT, TRADING_AGENT_PROMPT
from core.prompts import (
    CHAT_AGENT_SYSTEM_PROMPT,
    PRIVATE_PM_DECISION_JSON_PROMPT,
    PRIVATE_PM_SYSTEM_PROMPT,
    WYCKOFF_FUNNEL_SYSTEM_PROMPT,
)
from workflows.holding_diagnosis_llm import SYSTEM_PROMPT as HOLDING_SYSTEM_PROMPT


def test_python_prompts_forbid_banned_deterministic_terms():
    prompts = [
        WYCKOFF_FUNNEL_SYSTEM_PROMPT,
        PRIVATE_PM_SYSTEM_PROMPT,
        PRIVATE_PM_DECISION_JSON_PROMPT,
        CHAT_AGENT_SYSTEM_PROMPT,
        ANALYSIS_AGENT_PROMPT,
        TRADING_AGENT_PROMPT,
        HOLDING_SYSTEM_PROMPT,
    ]
    banned = ["必然", "保证", "无风险", "稳赚", "稳赢", "包赚"]
    for prompt in prompts:
        for word in banned:
            if word in prompt:
                # If a banned word exists in system instructions, it must be negated/prohibited.
                assert any(
                    neg in prompt
                    for neg in [
                        "禁止",
                        "不能",
                        "不得",
                        "不",
                        "没有",
                        "不用",
                        "绝不",
                        "非",
                        "无法",
                    ]
                )


def test_python_prompts_require_safety_mentions():
    # Tactical prompts must specify risk-management / invalidation conditions.
    tactical_prompts = [
        WYCKOFF_FUNNEL_SYSTEM_PROMPT,
        PRIVATE_PM_DECISION_JSON_PROMPT,
        TRADING_AGENT_PROMPT,
        HOLDING_SYSTEM_PROMPT,
    ]
    for prompt in tactical_prompts:
        assert any(x in prompt for x in ["失效", "风控", "风险", "止损", "Plan B", "底线", "防守"])
