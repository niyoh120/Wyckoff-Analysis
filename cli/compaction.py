"""上下文压缩 — TUI 和 headless agent loop 共用。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from cli.model_metadata import UNKNOWN_MODEL_CONTEXT_WINDOW, infer_context_window

logger = logging.getLogger(__name__)

COMPACT_RESERVE_RATIO = 0.25
MIN_COMPACT_RESERVE_TOKENS = 16_384
MAX_COMPACT_RESERVE_TOKENS = 32_768
TAIL_KEEP = 4
DEFAULT_RECENT_KEEP_TOKENS = 20_000
MIN_RECENT_KEEP_TOKENS = 4_000

_CODE_RE = re.compile(r"\d{6}")


def resolve_context_window(model_name: str = "", context_window: int | None = None) -> int:
    try:
        configured = int(context_window or 0)
    except (TypeError, ValueError):
        configured = 0
    if configured > 0:
        return configured
    return infer_context_window(model_name) if model_name else UNKNOWN_MODEL_CONTEXT_WINDOW


def get_compact_reserve_tokens(context_window: int) -> int:
    """Return the safety budget kept free for prompts, tools, and output."""

    window = max(context_window, 1)
    ratio_reserve = int(window * COMPACT_RESERVE_RATIO)
    clamped_reserve = max(MIN_COMPACT_RESERVE_TOKENS, min(ratio_reserve, MAX_COMPACT_RESERVE_TOKENS))
    return min(clamped_reserve, window // 2)


def get_compact_threshold(model_name: str = "", context_window: int | None = None) -> int:
    window = resolve_context_window(model_name, context_window)
    return max(1, window - get_compact_reserve_tokens(window))


def get_recent_keep_tokens(model_name: str = "", context_window: int | None = None) -> int:
    """Return the recent-context budget to keep after compaction."""

    threshold = get_compact_threshold(model_name, context_window)
    if threshold <= MIN_RECENT_KEEP_TOKENS * 2:
        return max(1_000, threshold // 2)
    return min(DEFAULT_RECENT_KEEP_TOKENS, max(MIN_RECENT_KEEP_TOKENS, threshold // 2))


# ---------------------------------------------------------------------------
# Token 估算
# ---------------------------------------------------------------------------


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += max(len(content) // 2, len(content.encode("utf-8")) // 3)
        for tc in m.get("tool_calls", []):
            args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
            total += len(args_str) // 3
    return total


def _estimate_message_tokens(message: dict[str, Any]) -> int:
    return estimate_tokens([message])


# ---------------------------------------------------------------------------
# 分层消息序列化（保留工具结果中的关键数据）
# ---------------------------------------------------------------------------


def _summarize_tool_result(name: str, content: str, max_len: int = 400) -> str:
    """从工具返回结果中提取关键信息而不是粗暴截断。"""
    if len(content) <= max_len:
        return content

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content[:max_len] + "…"

    # analyze_stock: 按返回结构区分 price/diagnose 模式
    if name == "analyze_stock" and isinstance(data, dict):
        if "data" in data and isinstance(data.get("data"), list):
            kept: dict[str, Any] = {}
            for key in ("code", "latest_close", "latest_date", "days"):
                if key in data:
                    kept[key] = data[key]
            kept["data"] = data["data"][-5:]
            return json.dumps(kept, ensure_ascii=False)[:max_len]
        kept = {}
        for key in (
            "code",
            "name",
            "channel",
            "phase",
            "trigger_signals",
            "exit_signals",
            "health",
            "positions",
            "message",
        ):
            if key in data:
                kept[key] = data[key]
        if kept:
            return json.dumps(kept, ensure_ascii=False)[:max_len]

    if name == "analyze_stock" and isinstance(data, list):
        return json.dumps(data[-5:], ensure_ascii=False)[:max_len]

    # portfolio — 按结构区分 view/diagnose
    if name == "portfolio" and isinstance(data, dict):
        if "diagnostics" in data:
            kept = {}
            for key in (
                "portfolio_id",
                "position_count",
                "successful_count",
                "failed_count",
                "free_cash",
                "diagnostics",
            ):
                if key in data:
                    kept[key] = data[key]
            if kept:
                return json.dumps(kept, ensure_ascii=False)[:max_len]
        else:
            kept = {}
            for key in ("portfolio_id", "free_cash", "position_count", "positions", "message"):
                if key in data:
                    kept[key] = data[key]
            if kept:
                return json.dumps(kept, ensure_ascii=False)[:max_len]

    # 通用：保留 error/message/status 等顶层键
    if isinstance(data, dict):
        kept = {}
        for key in ("error", "message", "status", "code", "name", "result"):
            if key in data:
                kept[key] = data[key]
        if kept:
            return json.dumps(kept, ensure_ascii=False)[:max_len]

    return content[:max_len] + "…"


SHRINK_THRESHOLD = 800


def shrink_stale_tool_results(messages: list[dict[str, Any]]) -> int:
    """就地压缩旧轮次的大 tool result，保留最新一轮完整结果。

    返回压缩掉的字符数。只影响 messages in-memory，scratchpad 原始记录不变。
    """
    boundary = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            boundary = i
            break
    saved = 0
    for i in range(boundary):
        m = messages[i]
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        if len(content) <= SHRINK_THRESHOLD:
            continue
        shrunk = _summarize_tool_result(m.get("name", ""), content, max_len=600)
        saved += len(content) - len(shrunk)
        m["content"] = shrunk
    return saved


def serialize_messages_for_compaction(messages: list[dict[str, Any]]) -> str:
    """将消息序列化为压缩输入，工具结果做智能摘要而非粗暴截断。"""
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "")
        if role == "tool":
            name = m.get("name", "tool")
            content = m.get("content", "")
            summary = _summarize_tool_result(name, content)
            lines.append(f"[tool:{name}] {summary}")
        elif role == "assistant" and m.get("tool_calls"):
            calls = ", ".join(
                f"{tc.get('name', '?')}({json.dumps(tc.get('args', {}), ensure_ascii=False)[:80]})"
                for tc in m["tool_calls"]
            )
            lines.append(f"[assistant:tool_call] {calls}")
            if m.get("content"):
                lines.append(f"[assistant] {m['content']}")
        else:
            content = m.get("content", "") or ""
            lines.append(f"[{role}] {content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory Flush — 压缩前提取持久事实
# ---------------------------------------------------------------------------

_FLUSH_PROMPT = """请从以下对话片段中提取用户的持久偏好或重要事实，每条一行。
只提取以下类型的信号：
- 投资偏好（如"不买ST股"、"偏好大盘蓝筹"、"不追涨"）
- 风险偏好（如"止损线8%"、"仓位不超过20%"）
- 重要结论（如"000001适合长期持有"、"银行板块看好"）

如果没有值得记忆的偏好或事实，只输出"无"。
不要提取临时操作指令或工具调用细节。"""


def flush_memory_before_compaction(
    messages: list[dict[str, Any]],
    provider: Any,
) -> None:
    """在压缩前，用 LLM 从待压缩消息中提取 preference 存入记忆。"""
    try:
        from cli.memory import extract_stock_codes
        from integrations.local_db import save_memory
    except ImportError:
        return

    # 只从 user/assistant 消息中提取，跳过工具结果
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "")
        if role in ("user", "assistant"):
            content = m.get("content", "")
            if content and len(content) > 10:
                lines.append(f"[{role}] {content[:300]}")
    if len(lines) < 2:
        return

    text = "\n".join(lines[-20:])
    try:
        chunks = list(
            provider.chat_stream(
                [{"role": "user", "content": text}],
                [],
                _FLUSH_PROMPT,
            )
        )
        result = "".join(c.get("text", "") for c in chunks if c.get("type") == "text_delta")
        if not result or "无" in result.strip()[:5]:
            return

        all_text = " ".join(m.get("content", "") or "" for m in messages)
        codes = extract_stock_codes(all_text)

        _skip_phrases = ("摘要", "压缩", "总结", "对话历史", "分析讨论", "上下文")
        for line in result.strip().split("\n"):
            line = line.strip().lstrip("- ").strip()
            if not line or len(line) < 5 or "无" in line[:3]:
                continue
            if any(p in line for p in _skip_phrases):
                continue
            save_memory("preference", line, codes=",".join(codes[:10]))
    except Exception:
        logger.debug("memory flush before compaction failed", exc_info=True)


# ---------------------------------------------------------------------------
# 压缩 prompt
# ---------------------------------------------------------------------------

COMPACTION_PROMPT = """请将以下对话历史总结为简洁的上下文摘要，保留关键信息：
1. 用户的目标和意图
2. 已完成的操作和结果（保留具体股票代码、价格、信号等数据）
3. 工具调用的关键发现和结论
4. 未完成的任务

用中文输出，控制在 500 字以内。只输出摘要，不要其他内容。"""


# ---------------------------------------------------------------------------
# 执行压缩
# ---------------------------------------------------------------------------


def _expand_tail_for_tool_refs(messages: list[dict[str, Any]], tail_start: int) -> int:
    """向前扩展 tail 边界，确保 tail 中 tool 消息引用的 call_id 对应的 assistant 消息也在 tail 内。"""
    tail_tool_call_ids: set[str] = set()
    for m in messages[tail_start:]:
        if m.get("role") == "tool" and m.get("tool_call_id"):
            tail_tool_call_ids.add(m["tool_call_id"])
    if not tail_tool_call_ids:
        return tail_start

    for i in range(tail_start - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            ids_in_msg = {tc.get("id") for tc in m["tool_calls"] if tc.get("id")}
            if ids_in_msg & tail_tool_call_ids:
                tail_start = i
                tail_tool_call_ids -= ids_in_msg
                # 继续检查新纳入的 tool 消息是否又引入新依赖
                for j in range(i + 1, len(messages)):
                    mj = messages[j]
                    if mj.get("role") == "tool" and mj.get("tool_call_id"):
                        tail_tool_call_ids.add(mj["tool_call_id"])
                    if mj.get("role") == "assistant" and mj.get("tool_calls"):
                        for tc in mj["tool_calls"]:
                            if tc.get("id"):
                                tail_tool_call_ids.discard(tc["id"])
        if not tail_tool_call_ids:
            break
    return tail_start


def find_tail_start_by_token_budget(
    messages: list[dict[str, Any]],
    keep_recent_tokens: int,
    *,
    min_tail_messages: int = TAIL_KEEP,
) -> int:
    """Find a tail boundary that keeps recent context by token budget.

    The boundary is message-based and never starts on a tool result. The caller
    should still pass the result through `_expand_tail_for_tool_refs` so tool
    result messages keep their matching assistant tool calls.
    """

    if not messages:
        return 0

    min_tail_start = max(0, len(messages) - max(1, min_tail_messages))
    accumulated = 0
    tail_start = min_tail_start

    for i in range(len(messages) - 1, -1, -1):
        accumulated += _estimate_message_tokens(messages[i])
        if accumulated >= keep_recent_tokens:
            tail_start = i
            break
    else:
        tail_start = 0

    tail_start = min(tail_start, min_tail_start)

    while tail_start > 0 and messages[tail_start].get("role") == "tool":
        tail_start -= 1

    return _expand_tail_for_tool_refs(messages, tail_start)


def build_local_context_summary(messages: list[dict[str, Any]], *, max_chars: int = 1200) -> str:
    """Build a deterministic summary for surfaces that cannot run a summary LLM.

    This is intentionally compact and factual. It is not a replacement for the
    LLM compactor used by the CLI, but it gives UI-backed sessions a stable
    checkpoint when their provider/session layer owns the model call.
    """

    if not messages:
        return "无前序对话。"

    user_goals: list[str] = []
    assistant_notes: list[str] = []
    tool_notes: list[str] = []
    codes: list[str] = []

    def _add_code_matches(text: str) -> None:
        for code in _CODE_RE.findall(text or ""):
            if code not in codes:
                codes.append(code)

    for msg in messages:
        role = msg.get("role", "")
        content = str(msg.get("content", "") or "").strip()
        _add_code_matches(content)
        if role == "user" and content:
            user_goals.append(content[:180])
        elif role == "assistant" and content:
            assistant_notes.append(content[:220])
        elif role == "tool" and content:
            tool_notes.append(_summarize_tool_result(msg.get("name", ""), content, max_len=220))

    lines = ["前序对话已压缩为摘要。"]
    if codes:
        lines.append(f"涉及标的：{', '.join(codes[:12])}")
    if user_goals:
        lines.append("用户关注：")
        for item in user_goals[-6:]:
            lines.append(f"- {item}")
    if assistant_notes:
        lines.append("已给出的主要结论：")
        for item in assistant_notes[-6:]:
            lines.append(f"- {item}")
    if tool_notes:
        lines.append("工具结果要点：")
        for item in tool_notes[-4:]:
            lines.append(f"- {item}")

    summary = "\n".join(lines)
    return summary if len(summary) <= max_chars else summary[: max_chars - 1].rstrip() + "…"


def compact_messages(
    messages: list[dict[str, Any]],
    provider: Any,
    model_name: str = "",
    context_window: int | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """检查并执行上下文压缩。

    Returns (messages, compacted) — 如果未压缩则原样返回。
    """
    threshold = get_compact_threshold(model_name, context_window)
    if len(messages) <= TAIL_KEEP + 2 or estimate_tokens(messages) <= threshold:
        return messages, False

    tail_start = find_tail_start_by_token_budget(messages, get_recent_keep_tokens(model_name, context_window))
    if tail_start <= 2:
        return messages, False

    head = messages[:tail_start]
    tail = messages[tail_start:]

    # 压缩前先提取持久偏好到记忆
    flush_memory_before_compaction(head, provider)

    head_text = serialize_messages_for_compaction(head)

    try:
        chunks = list(
            provider.chat_stream(
                [{"role": "user", "content": head_text}],
                [],
                COMPACTION_PROMPT,
            )
        )
        summary = "".join(c.get("text", "") for c in chunks if c.get("type") == "text_delta")
        if summary and len(summary) >= 20:
            compacted = [
                {"role": "user", "content": f"[对话摘要]\n{summary}"},
                {"role": "assistant", "content": "好的，我已了解之前的对话上下文，请继续。"},
            ] + tail
            return compacted, True
    except Exception:
        logger.debug("compaction LLM call failed", exc_info=True)

    return messages, False
