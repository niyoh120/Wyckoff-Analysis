from __future__ import annotations

from agents.session_manager import build_compacted_chat_history


def _make_history(turns: int) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for i in range(turns):
        messages.append({"role": "user", "content": f"帮我看看 600{i % 10:03d} " + "量价关系 " * 120})
        messages.append({"role": "assistant", "content": f"结论 {i}: 先看供需，不追涨。 " + "等待确认 " * 120})
    return messages


def test_reading_room_history_compacts_to_summary_and_tail():
    messages = _make_history(16)

    compacted, meta = build_compacted_chat_history(messages, "gpt-3.5-turbo")

    assert meta is not None
    assert compacted[0]["role"] == "user"
    assert compacted[0]["content"].startswith("[读盘室对话摘要]")
    assert "工具实时返回" in compacted[0]["content"]
    assert compacted[1]["role"] == "assistant"
    assert compacted[-1] == messages[-1]
    assert meta["before_messages"] == len(messages)
    assert meta["after_messages"] < len(messages)
    assert meta["tail_messages"] >= 4


def test_reading_room_history_stays_intact_when_small():
    messages = [
        {"role": "user", "content": "帮我看看 000001"},
        {"role": "assistant", "content": "先取数据再判断。"},
    ]

    compacted, meta = build_compacted_chat_history(messages, "gpt-3.5-turbo")

    assert meta is None
    assert compacted is messages
