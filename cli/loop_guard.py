"""Shared guardrails and constants for the agent loop."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from cli.screen_intent import (
    stock_screen_candidate_request_hint,
    stock_screen_style_target_hint,
    stock_screen_suggested_args,
    stock_screen_temporal_buy_hint,
    stock_screen_theme_hint,
    stock_screen_watch_hint,
)

MAX_TOOL_ROUNDS = 15
MAX_INCOMPLETE_TOOL_RETRIES = 2
DOOM_LOOP_WINDOW = 6
DOOM_LOOP_THRESHOLD = 3
DOOM_LOOP_EXEMPT = frozenset({"check_background_tasks"})


@dataclass(frozen=True)
class TurnExpectation:
    """A tool call the loop considers mandatory for the current turn."""

    required_tool: str
    reason: str
    suggested_args: dict[str, str] = field(default_factory=dict)
    required_args: dict[str, str] = field(default_factory=dict)


_PORTFOLIO_SUBJECT_HINTS = (
    "持仓",
    "仓位",
    "持股",
    "账户",
    "我买",
)

_PORTFOLIO_VIEW_HINTS = (
    "读",
    "读取",
    "看",
    "查",
    "列",
    "列表",
    "情况",
    "有什么",
    "啥",
    "什么",
    "多少",
)

_PORTFOLIO_DIAGNOSE_HINTS = (
    "怎么样",
    "健康",
    "体检",
    "诊断",
    "审",
    "分析",
    "风险",
    "处理",
    "去留",
    "要不要动",
)

_GENERIC_DIAGNOSE_HINTS = (
    "分析",
    "走势",
    "未来走势",
    "日线",
)

_PORTFOLIO_FOLLOWUP_DIAGNOSE_HINTS = (
    "体检",
    "健康",
    "诊断",
    "审",
)

_AFFIRMATIVE_PHRASES = (
    "要",
    "要的",
    "好的",
    "可以",
    "行",
    "来吧",
    "嗯",
    "好",
)

_PORTFOLIO_FOLLOWUP_REFERENCES = (
    "他们",
    "它们",
    "这些",
    "这几个",
    "几个股票",
    "几只",
    "上面",
    "上述",
    "这些票",
    "这几只",
    "我的持仓",
    "持仓股票",
)

_PORTFOLIO_CONTEXT_MARKERS = (
    "持仓",
    "仓位",
    "持股",
    "成本价",
    "买入日",
    "代码 | 名称 | 持股",
    "总可用",
    "现金",
    "portfolio",
)

_STOCK_SCREEN_HINTS = (
    "选股",
    "筛选",
    "筛股票",
    "扫描",
    "好股票",
    "好股",
    "推荐股票",
    "推荐标的",
    "买什么",
    "买哪",
)

_STOCK_SCREEN_TARGET_HINTS = (
    "机会",
    "机会池",
    "候选",
)

_STOCK_SCREEN_TARGET_ACTIONS = (
    "给",
    "找",
    "筛",
    "挑",
    "跑",
    "扫描",
    "推荐",
    "有什么",
    "哪些",
)

_STOCK_SCREEN_CONTEXT_HINTS = (
    "股票",
    "标的",
    "票",
    "a股",
    "a 股",
)

_ETF_SCREEN_CONTEXT_HINTS = (
    "etf",
    "基金",
    "行业基金",
)

_ETF_SCREEN_INTENT_HINTS = (
    "机会",
    "候选",
    "筛",
    "筛选",
    "扫描",
    "推荐",
    "强势",
    "低吸",
    "主线",
)

_THEME_SCREEN_INTENT_HINTS = (
    "机会",
    "机会池",
    "候选",
    "筛",
    "筛选",
    "扫描",
    "推荐",
    "强势",
    "低吸",
    "主线",
    "标的",
    "最强",
    "领涨",
    "龙头",
    "强度",
    "短线",
    "起爆",
)

_STOCK_SCREEN_INTENT_HINTS = (
    "推荐",
    "机会",
    "值得",
    "值得复核",
    "值得关注",
    "值得跟踪",
    "重点跟踪",
    "复核",
    "风险边界",
    "挑",
)

_STOCK_SCREEN_STYLE_HINTS = (
    "强势",
    "趋势",
    "低吸",
    "右侧",
    "左侧",
    "稳健",
)

_STOCK_SCREEN_REVIEW_HINTS = (
    "过去",
    "之前",
    "历史",
    "表现",
    "复盘",
    "推荐记录",
)

_AI_REPORT_HINTS = (
    "研报",
    "报告",
    "复核",
    "审讯",
)

_AI_REPORT_DIRECT_HINTS = (
    "研报",
    "报告",
    "审讯",
)

_AI_REPORT_ACTION_HINTS = (
    "继续",
    "下一步",
    "往下",
    "生成",
    "开始",
    "做吧",
    "跑吧",
)

_AI_REPORT_AFFIRMATIVE_PHRASES = (
    "好",
    "好的",
    "可以",
)

_AI_REPORT_CONTEXT_MARKERS = (
    "generate_ai_report",
    "tool_handoff",
    "ready_for_ai_review",
    "可进入 ai 研报复核",
    "首选候选已通过市场闸门",
    "selection_brief",
    "review_targets",
    "symbols_for_report",
)

_STRATEGY_DECISION_CONTEXT_TOOLS = ("screen_stocks", "generate_ai_report")

_STRATEGY_DECISION_DELIVERY_HINTS = (
    "攻防",
    "风险边界",
    "买卖计划",
    "操作计划",
    "交易计划",
    "止损",
    "止盈",
    "入场",
    "买点",
    "生死线",
)

_EXPLANATION_ONLY_HINTS = (
    "是什么",
    "什么意思",
    "啥意思",
    "为什么",
    "原理",
    "逻辑",
    "规则",
    "方法",
    "流程",
    "框架",
    "标准",
    "口径",
    "怎么做",
    "如何做",
    "怎么选",
    "如何选",
    "讲讲",
    "介绍",
    "解释",
    "说明",
)

_CONCRETE_DATA_HINTS = (
    "我的",
    "我买",
    "我持",
    "账户里",
    "这些",
    "这几个",
    "上述",
    "上面",
    "今天",
    "最新",
    "本轮",
    "这轮",
    "创业板",
    "科创",
    "主板",
)

_TOOL_CN_NAMES = {
    "portfolio": "持仓数据",
    "analyze_stock": "个股分析",
    "get_market_overview": "大盘水温",
    "screen_stocks": "全市场扫描",
    "generate_ai_report": "AI 研报",
    "generate_strategy_decision": "攻防决策",
    "run_backtest": "回测",
}

_CURRENT_USER_OPEN = "<current-user-message>"
_CURRENT_USER_CLOSE = "</current-user-message>"


def _normalize_text(text: str) -> str:
    return str(text or "").strip().lower()


def _strip_recall_context(text: str) -> str:
    raw = str(text or "")
    start = raw.rfind(_CURRENT_USER_OPEN)
    end = raw.rfind(_CURRENT_USER_CLOSE)
    if start >= 0 and end > start:
        start += len(_CURRENT_USER_OPEN)
        return raw[start:end].strip()
    return raw


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    return _strip_recall_context(content) if isinstance(content, str) else ""


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("_system_notification"):
            continue
        if message.get("role") == "user":
            text = _message_text(message)
            if text:
                return _normalize_text(text)
    return ""


def _recent_context_text(messages: list[dict[str, Any]], *, limit: int = 4) -> str:
    pieces: list[str] = []
    for message in messages[-limit:]:
        if message.get("_system_notification"):
            continue
        text = _message_text(message)
        if text:
            pieces.append(_normalize_text(text))
    return "\n".join(pieces)


def resolve_turn_expectation(messages: list[dict[str, Any]]) -> TurnExpectation | None:
    """Infer whether this turn must call a specific tool before answering."""

    if not messages:
        return None
    if messages[-1].get("_system_notification"):
        return None

    last_user = _last_user_text(messages)
    if not last_user:
        return None

    previous_context = _recent_context_text(messages[:-1], limit=4)

    if _portfolio_diagnose_expected(last_user):
        return TurnExpectation(
            required_tool="portfolio",
            reason="持仓体检需要先读取真实持仓数据。",
            suggested_args={"mode": "diagnose"},
        )

    if _portfolio_view_expected(last_user):
        return TurnExpectation(
            required_tool="portfolio",
            reason="持仓列表查询需要先读取真实持仓数据。",
            suggested_args={"mode": "view"},
        )

    if _stock_screen_expected(last_user):
        screen_args = stock_screen_suggested_args(last_user)
        return TurnExpectation(
            required_tool="screen_stocks",
            reason="真实选股/候选请求需要先运行筛选工具。",
            suggested_args=screen_args,
            required_args=_stock_screen_required_args(screen_args),
        )

    if _ai_report_direct_expected(last_user):
        return TurnExpectation(
            required_tool="generate_ai_report",
            reason="AI 研报任务需要先运行真实研报工具。",
        )

    if _ai_report_expected(last_user, previous_context):
        return TurnExpectation(
            required_tool="generate_ai_report",
            reason="上一轮已有筛股候选，这一轮需要先生成真实 AI 研报。",
        )

    if _strategy_decision_direct_expected(last_user):
        return TurnExpectation(
            required_tool="generate_strategy_decision",
            reason="攻防/买卖计划任务需要先运行真实组合攻防复核。",
        )

    if (
        any(hint in last_user for hint in _PORTFOLIO_FOLLOWUP_DIAGNOSE_HINTS)
        or (
            any(hint in last_user for hint in _GENERIC_DIAGNOSE_HINTS)
            and any(ref in last_user for ref in _PORTFOLIO_FOLLOWUP_REFERENCES)
        )
    ) and any(marker in previous_context for marker in _PORTFOLIO_CONTEXT_MARKERS):
        return TurnExpectation(
            required_tool="portfolio",
            reason="上一轮上下文已经明确在讨论持仓，这一轮需要先读取真实持仓数据。",
            suggested_args={"mode": "diagnose"},
        )

    if (
        last_user in _AFFIRMATIVE_PHRASES
        and (
            any(hint in previous_context for hint in _GENERIC_DIAGNOSE_HINTS)
            or any(hint in previous_context for hint in _PORTFOLIO_FOLLOWUP_DIAGNOSE_HINTS)
        )
        and any(marker in previous_context for marker in _PORTFOLIO_CONTEXT_MARKERS)
    ):
        return TurnExpectation(
            required_tool="portfolio",
            reason="用户承接上一轮持仓体检/分析邀请，需要先读取真实持仓数据。",
            suggested_args={"mode": "diagnose"},
        )

    return None


def resolve_progressive_turn_expectation(
    messages: list[dict[str, Any]],
    used_tools: Iterable[str | tuple[str, dict]],
) -> TurnExpectation | None:
    """Infer mandatory follow-up tools after earlier tools in the same turn."""

    last_user = _last_user_text(messages)
    if not last_user or _explanation_only_question(last_user):
        return None
    used_names = _used_tool_names(used_tools)
    if "generate_strategy_decision" in used_names:
        return None
    if not used_names.intersection(_STRATEGY_DECISION_CONTEXT_TOOLS):
        return None
    if not _strategy_decision_expected(last_user):
        return None
    return TurnExpectation(
        required_tool="generate_strategy_decision",
        reason="用户要求候选攻防/风险边界，需要在筛选或研报后生成真实组合攻防复核。",
    )


def _used_tool_names(used_tools: Iterable[str | tuple[str, dict]]) -> set[str]:
    names: set[str] = set()
    for entry in used_tools:
        names.add(entry[0] if isinstance(entry, tuple) else entry)
    return names


def _portfolio_view_expected(text: str) -> bool:
    return (
        not _explanation_only_question(text)
        and _mentions_portfolio_subject(text)
        and any(hint in text for hint in _PORTFOLIO_VIEW_HINTS)
    )


def _portfolio_diagnose_expected(text: str) -> bool:
    return (
        not _explanation_only_question(text)
        and _mentions_portfolio_subject(text)
        and any(hint in text for hint in _PORTFOLIO_DIAGNOSE_HINTS)
    )


def _mentions_portfolio_subject(text: str) -> bool:
    return any(hint in text for hint in _PORTFOLIO_SUBJECT_HINTS)


def _stock_screen_expected(text: str) -> bool:
    if _explanation_only_question(text):
        return False
    if any(hint in text for hint in _STOCK_SCREEN_REVIEW_HINTS):
        return False
    if any(hint in text for hint in _STOCK_SCREEN_HINTS):
        return True
    if stock_screen_temporal_buy_hint(text):
        return True
    if stock_screen_watch_hint(text):
        return True
    if stock_screen_candidate_request_hint(text):
        return True
    if stock_screen_style_target_hint(text):
        return True
    if _etf_screen_expected(text):
        return True
    if _theme_screen_expected(text):
        return True
    if any(hint in text for hint in _STOCK_SCREEN_TARGET_HINTS) and any(
        hint in text for hint in _STOCK_SCREEN_TARGET_ACTIONS
    ):
        return True
    if _stock_screen_style_target_expected(text) and any(hint in text for hint in _STOCK_SCREEN_TARGET_ACTIONS):
        return True
    return any(hint in text for hint in _STOCK_SCREEN_CONTEXT_HINTS) and any(
        hint in text for hint in (*_STOCK_SCREEN_INTENT_HINTS, *_STOCK_SCREEN_STYLE_HINTS)
    )


def _etf_screen_expected(text: str) -> bool:
    return any(hint in text for hint in _ETF_SCREEN_CONTEXT_HINTS) and any(
        hint in text for hint in _ETF_SCREEN_INTENT_HINTS
    )


def _theme_screen_expected(text: str) -> bool:
    return bool(stock_screen_theme_hint(text)) and any(hint in text for hint in _THEME_SCREEN_INTENT_HINTS)


def _stock_screen_style_target_expected(text: str) -> bool:
    return any(hint in text for hint in _STOCK_SCREEN_STYLE_HINTS) and any(
        hint in text for hint in _STOCK_SCREEN_CONTEXT_HINTS
    )


def _stock_screen_required_args(args: dict[str, str]) -> dict[str, str]:
    required: dict[str, str] = {}
    for key in ("style", "theme", "limit", "financial_metrics"):
        if value := args.get(key):
            required[key] = value
    if board := args.get("board"):
        if board != "all":
            required["board"] = board
    return required


def _ai_report_expected(text: str, previous_context: str) -> bool:
    if _explanation_only_question(text):
        return False
    if not any(marker in previous_context for marker in _AI_REPORT_CONTEXT_MARKERS):
        return False
    return (
        any(hint in text for hint in _AI_REPORT_HINTS)
        or any(hint in text for hint in _AI_REPORT_ACTION_HINTS)
        or text in _AI_REPORT_AFFIRMATIVE_PHRASES
    )


def _ai_report_direct_expected(text: str) -> bool:
    if _explanation_only_question(text):
        return False
    return any(hint in text for hint in _AI_REPORT_DIRECT_HINTS) and any(
        hint in text for hint in _AI_REPORT_ACTION_HINTS
    )


def _strategy_decision_expected(text: str) -> bool:
    return any(hint in text for hint in _STRATEGY_DECISION_DELIVERY_HINTS)


def _strategy_decision_direct_expected(text: str) -> bool:
    return not _explanation_only_question(text) and _strategy_decision_expected(text)


def _explanation_only_question(text: str) -> bool:
    return any(hint in text for hint in _EXPLANATION_ONLY_HINTS) and not any(
        hint in text for hint in _CONCRETE_DATA_HINTS
    )


def missing_required_tool(
    expectation: TurnExpectation | None,
    used_tools: Iterable[str | tuple[str, dict]],
) -> bool:
    if expectation is None:
        return False
    req_args = expectation.required_args
    for entry in used_tools:
        if isinstance(entry, tuple):
            name, args = entry
        else:
            name, args = entry, {}
        if name != expectation.required_tool:
            continue
        if not req_args:
            return False
        if _tool_args_match(args, req_args):
            return False
    return True


def _tool_args_match(args: dict[str, Any], required_args: dict[str, str]) -> bool:
    return all(_tool_arg_value_matches(args.get(key), expected) for key, expected in required_args.items())


def _tool_arg_value_matches(actual: Any, expected: str) -> bool:
    if actual == expected:
        return True
    actual_text = _normalized_tool_arg_value(actual)
    expected_text = _normalized_tool_arg_value(expected)
    return bool(expected_text and actual_text == expected_text)


def _normalized_tool_arg_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in {"true", "false"}:
            return text.lower()
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, (list, tuple, set)):
            return ",".join(str(item).strip() for item in parsed if str(item).strip())
        return text
    return str(value if value is not None else "").strip()


def build_retry_user_message(expectation: TurnExpectation, assistant_text: str = "") -> str:
    """Synthetic follow-up injected when the model skipped a mandatory tool."""

    tool_name = _TOOL_CN_NAMES.get(expectation.required_tool, expectation.required_tool)
    body = str(assistant_text or "").strip()
    if body:
        if _looks_like_plan_only(body):
            lead = "你刚才只给了计划，还没有真正执行。"
        else:
            lead = "你刚才直接给了文本回答，但没有先拿真实数据。"
    else:
        lead = "这一轮没有返回有效工具调用。"
    if expectation.required_args:
        display_args = {**expectation.suggested_args, **expectation.required_args}
        pairs = ", ".join(f'{k}="{v}"' for k, v in display_args.items())
        call_hint = f"`{expectation.required_tool}({pairs})`"
    elif expectation.suggested_args:
        pairs = ", ".join(f'{k}="{v}"' for k, v in expectation.suggested_args.items())
        call_hint = f"`{expectation.required_tool}`（建议参数：{pairs}，可按上下文调整）"
    else:
        call_hint = f"`{expectation.required_tool}`"
    return (
        f"{lead}{expectation.reason}"
        f" 现在必须先调用 {call_hint}（{tool_name}）拿到真实数据，"
        "再继续回答。不要重复计划，直接执行第一步。"
    )


def build_retry_exhausted_warning(expectation: TurnExpectation, retries: int) -> str:
    tool_name = _TOOL_CN_NAMES.get(expectation.required_tool, expectation.required_tool)
    return f"⚠ 模型连续 {retries} 次没有调用必需工具 `{expectation.required_tool}`（{tool_name}），以下回答可能不可靠。"


def _looks_like_plan_only(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    if "计划" in normalized:
        return True
    markers = (
        "第一步",
        "第二步",
        "第三步",
        "先",
        "再",
        "然后",
        "接着",
        "现在开第一刀",
    )
    numbered = any(token in normalized for token in ("1.", "1、", "2.", "2、", "3.", "3、"))
    return numbered and any(marker in normalized for marker in markers)


# ---------------------------------------------------------------------------
# Doom-loop detection
# ---------------------------------------------------------------------------


def _jaccard_similarity(s1: str, s2: str) -> float:
    """计算两个字符串的 Jaccard 相似度（字符 3-gram）。"""
    if not s1 or not s2:
        return 0.0
    grams1 = {s1[i : i + 3] for i in range(max(len(s1) - 2, 1))}
    grams2 = {s2[i : i + 3] for i in range(max(len(s2) - 2, 1))}
    if not grams1 or not grams2:
        return 0.0
    return len(grams1 & grams2) / len(grams1 | grams2)


def check_doom_loop(
    recent_calls: list[tuple[str, int]],
    name: str,
    args: dict[str, Any],
    *,
    recent_args_texts: list[str] | None = None,
    similarity_threshold: float = 0.8,
) -> bool:
    """Track a tool call and return True if a doom-loop is detected.

    Mutates *recent_calls* in place: appends the new entry and trims to
    ``DOOM_LOOP_WINDOW``.  Returns ``True`` when the same (name, args_hash)
    appears >= ``DOOM_LOOP_THRESHOLD`` times in the window,
    OR when similar args (Jaccard >= threshold) appear >= threshold times.
    """
    if name in DOOM_LOOP_EXEMPT:
        return False
    import json as _json

    args_text = _json.dumps(args, sort_keys=True, ensure_ascii=False)
    args_hash = hash(args_text)
    recent_calls.append((name, args_hash))
    if len(recent_calls) > DOOM_LOOP_WINDOW:
        recent_calls.pop(0)

    if recent_args_texts is not None:
        recent_args_texts.append(args_text)
        if len(recent_args_texts) > DOOM_LOOP_WINDOW:
            recent_args_texts.pop(0)

    # 精确匹配
    if recent_calls.count((name, args_hash)) >= DOOM_LOOP_THRESHOLD:
        return True

    # 语义相似匹配：检查同工具的参数是否"换汤不换药"
    # 短参数（< 50字符）跳过 Jaccard——短 JSON 天然高相似度导致误判批量调用
    if recent_args_texts is not None and len(args_text) >= 50:
        same_tool_texts = [t for (n, _), t in zip(recent_calls, recent_args_texts) if n == name]
        similar_count = sum(1 for t in same_tool_texts if _jaccard_similarity(args_text, t) >= similarity_threshold)
        if similar_count >= DOOM_LOOP_THRESHOLD:
            return True

    return False
