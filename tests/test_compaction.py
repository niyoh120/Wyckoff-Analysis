from __future__ import annotations

import json

from cli.compaction import (
    MAX_COMPACT_RESERVE_TOKENS,
    MIN_COMPACT_RESERVE_TOKENS,
    TAIL_KEEP,
    _expand_tail_for_tool_refs,
    _summarize_tool_result,
    build_local_context_summary,
    compact_messages,
    estimate_tokens,
    find_tail_start_by_token_budget,
    get_compact_reserve_tokens,
    get_compact_threshold,
    get_recent_keep_tokens,
    resolve_context_window,
    serialize_messages_for_compaction,
)
from cli.model_metadata import infer_context_window


class TestInferContextWindow:
    def test_deepseek(self):
        assert infer_context_window("deepseek-v4-flash") == 64_000

    def test_claude(self):
        assert infer_context_window("claude-sonnet-4-20260514") == 200_000

    def test_gemini_2(self):
        assert infer_context_window("gemini-2.5-flash") == 1_000_000

    def test_minimax_m3(self):
        assert infer_context_window("MiniMax-M3") == 1_000_000

    def test_unknown_model_uses_inference_default(self):
        assert infer_context_window("some-unknown-model") == 64_000

    def test_threshold_ratio(self):
        assert get_compact_threshold("claude-sonnet-4") == 200_000 - MAX_COMPACT_RESERVE_TOKENS

    def test_threshold_uses_configured_context_window(self):
        assert resolve_context_window("deepseek-chat", 100_000) == 100_000
        assert get_compact_threshold("deepseek-chat", 100_000) == 75_000

    def test_reserve_has_small_window_cap(self):
        assert get_compact_reserve_tokens(16_000) == 8_000
        assert get_compact_reserve_tokens(64_000) == MIN_COMPACT_RESERVE_TOKENS
        assert get_compact_reserve_tokens(1_000_000) == MAX_COMPACT_RESERVE_TOKENS

    def test_recent_keep_budget_scales_with_model(self):
        assert get_recent_keep_tokens("gpt-3.5-turbo") == 4_000
        assert get_recent_keep_tokens("deepseek-chat") == 20_000
        assert get_recent_keep_tokens("claude-sonnet-4") == 20_000


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens([]) == 0

    def test_text_message(self):
        tokens = estimate_tokens([{"role": "user", "content": "hello world"}])
        assert tokens > 0

    def test_tool_calls_counted(self):
        msg = {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"name": "analyze_stock", "args": {"code": "000001"}}],
        }
        assert estimate_tokens([msg]) > 0

    def test_chinese_text(self):
        tokens = estimate_tokens([{"role": "user", "content": "你好世界，今天天气不错"}])
        assert tokens > 0


class TestSummarizeToolResult:
    def test_short_content_unchanged(self):
        assert _summarize_tool_result("any_tool", "short") == "short"

    def test_analyze_stock_keeps_key_fields(self):
        data = {
            "code": "000001",
            "name": "平安银行",
            "phase": "accumulation",
            "trigger_signals": ["Spring"],
            "health": "STRONG",
            "extra_large_data": "x" * 2000,
        }
        result = _summarize_tool_result("analyze_stock", json.dumps(data, ensure_ascii=False))
        parsed = json.loads(result)
        assert parsed["code"] == "000001"
        assert parsed["health"] == "STRONG"
        assert "extra_large_data" not in parsed

    def test_analyze_stock_keeps_tail(self):
        prices = [{"date": f"2024-01-{i:02d}", "close": 10 + i} for i in range(1, 21)]
        result = _summarize_tool_result("analyze_stock", json.dumps(prices))
        parsed = json.loads(result)
        assert len(parsed) == 5
        assert parsed[0]["date"] == "2024-01-16"

    def test_generic_keeps_error_message(self):
        data = {"error": "timeout", "status": 500, "huge_payload": "y" * 2000}
        result = _summarize_tool_result("some_tool", json.dumps(data))
        parsed = json.loads(result)
        assert parsed["error"] == "timeout"
        assert parsed["status"] == 500
        assert "huge_payload" not in parsed

    def test_non_json_truncated(self):
        long_text = "a" * 1000
        result = _summarize_tool_result("any_tool", long_text)
        assert len(result) <= 401
        assert result.endswith("…")


class TestSerializeMessages:
    def test_tool_message(self):
        msgs = [{"role": "tool", "name": "analyze_stock", "content": '{"price":10}'}]
        text = serialize_messages_for_compaction(msgs)
        assert "[tool:analyze_stock]" in text

    def test_assistant_tool_call(self):
        msgs = [
            {
                "role": "assistant",
                "content": "查一下",
                "tool_calls": [{"name": "analyze_stock", "args": {"code": "000001"}}],
            }
        ]
        text = serialize_messages_for_compaction(msgs)
        assert "[assistant:tool_call]" in text
        assert "[assistant] 查一下" in text

    def test_user_message(self):
        msgs = [{"role": "user", "content": "帮我看看600519"}]
        text = serialize_messages_for_compaction(msgs)
        assert "[user] 帮我看看600519" in text


class TestTailBudget:
    def test_keeps_more_than_fixed_tail_when_budget_needs_it(self):
        msgs = [{"role": "user", "content": f"短消息 {i} " + "x" * 400} for i in range(12)]
        tail_start = find_tail_start_by_token_budget(msgs, keep_recent_tokens=900)
        assert tail_start < len(msgs) - TAIL_KEEP
        assert msgs[tail_start]["role"] != "tool"

    def test_local_summary_keeps_codes_and_recent_points(self):
        msgs = [
            {"role": "user", "content": "帮我看看 600519 和 000001"},
            {"role": "assistant", "content": "600519 还在高位震荡，000001 需要等量能确认。"},
        ]
        summary = build_local_context_summary(msgs)
        assert "600519" in summary
        assert "000001" in summary
        assert "高位震荡" in summary


class TestCompactMessages:
    class FakeProvider:
        def chat_stream(self, messages, tools, system_prompt):
            return [{"type": "text_delta", "text": "这是一段压缩后的摘要，包含了用户之前对股票的分析讨论。"}]

    def _make_messages(self, n: int) -> list[dict]:
        msgs = []
        for i in range(n):
            msgs.append(
                {"role": "user", "content": f"消息内容 {i} " + "这是一段很长的中文测试文本用来占据token空间" * 50}
            )
            msgs.append({"role": "assistant", "content": f"回复 {i} " + "这是助手的回复内容同样需要足够长" * 50})
        return msgs

    def test_no_compaction_when_short(self):
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        result, compacted = compact_messages(msgs, self.FakeProvider(), "deepseek")
        assert not compacted
        assert result is msgs

    def test_compaction_triggers_on_large_context(self):
        msgs = self._make_messages(30)
        result, compacted = compact_messages(msgs, self.FakeProvider(), "deepseek", context_window=16_000)
        assert compacted
        assert len(result) < len(msgs)
        assert result[0]["content"].startswith("[对话摘要]")
        assert result[-1] == msgs[-1]

    def test_tail_messages_preserved(self):
        msgs = self._make_messages(30)
        result, compacted = compact_messages(msgs, self.FakeProvider(), "deepseek")
        assert compacted
        tail = msgs[-TAIL_KEEP:]
        assert result[-TAIL_KEEP:] == tail

    def test_failed_compaction_returns_original(self):
        class FailProvider:
            def chat_stream(self, messages, tools, system_prompt):
                raise RuntimeError("LLM unavailable")

        msgs = self._make_messages(30)
        result, compacted = compact_messages(msgs, FailProvider(), "deepseek")
        assert not compacted
        assert result is msgs

    def test_failed_compaction_does_not_rewrite_original_tool_results(self):
        class FailProvider:
            def chat_stream(self, messages, tools, system_prompt):
                raise RuntimeError("LLM unavailable")

        large_tool_content = json.dumps({"payload": "x" * 5000})
        msgs = [{"role": "user", "content": "历史问题 " + "很长" * 1000}]
        msgs.append({"role": "tool", "name": "portfolio", "content": large_tool_content, "tool_call_id": "tc_old"})
        msgs.extend(self._make_messages(10))

        result, compacted = compact_messages(msgs, FailProvider(), "deepseek", context_window=8_000)

        assert not compacted
        assert result is msgs
        assert msgs[1]["content"] == large_tool_content

    def test_tool_call_refs_preserved(self):
        """tail 中 tool 消息引用的 call_id 对应 assistant 也被保留。"""
        msgs = self._make_messages(20)
        # 在倒数第5、6条位置插入 tool_call/tool 对
        msgs.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call_abc", "name": "analyze_stock", "args": {"code": "000001"}}],
            }
        )
        msgs.append({"role": "tool", "name": "analyze_stock", "content": '{"ok":true}', "tool_call_id": "call_abc"})
        msgs.append({"role": "assistant", "content": "分析完成"})
        msgs.append({"role": "user", "content": "谢谢"})
        # TAIL_KEEP=4 → 原始 tail 从 -4 开始，tool msg (倒数第3) 在 tail 内
        # 但对应 assistant tool_call (倒数第4) 不在原始 tail → 需要扩展
        result, compacted = compact_messages(msgs, self.FakeProvider(), "deepseek", context_window=16_000)
        assert compacted
        # 验证 call_id 引用完整性
        call_ids_defined = set()
        call_ids_referenced = set()
        for m in result:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if tc.get("id"):
                        call_ids_defined.add(tc["id"])
            if m.get("role") == "tool" and m.get("tool_call_id"):
                call_ids_referenced.add(m["tool_call_id"])
        assert call_ids_referenced <= call_ids_defined


class TestExpandTailForToolRefs:
    def test_no_tool_refs(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "bye"},
            {"role": "assistant", "content": "cya"},
        ]
        assert _expand_tail_for_tool_refs(msgs, 2) == 2

    def test_expands_to_include_assistant_with_tool_call(self):
        msgs = [
            {"role": "user", "content": "分析"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "t", "args": {}}]},
            {"role": "tool", "name": "t", "content": "ok", "tool_call_id": "c1"},
            {"role": "assistant", "content": "done"},
        ]
        # tail_start=2 → tail has tool msg referencing c1, assistant at idx 1 must be included
        assert _expand_tail_for_tool_refs(msgs, 2) == 1

    def test_no_expansion_when_ref_already_in_tail(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "t", "args": {}}]},
            {"role": "tool", "name": "t", "content": "ok", "tool_call_id": "c1"},
            {"role": "assistant", "content": "done"},
        ]
        # tail_start=1 → assistant with tool_call already in tail
        assert _expand_tail_for_tool_refs(msgs, 1) == 1
