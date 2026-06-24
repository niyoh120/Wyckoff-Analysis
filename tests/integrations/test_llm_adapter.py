from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest


def test_call_llm_via_litellm_builds_openai_compatible_request(monkeypatch):
    from integrations.llm_adapter import call_llm_via_litellm

    captured: dict = {}
    fake_litellm = ModuleType("litellm")

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="  ok  "))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
        )

    fake_litellm.completion = fake_completion
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    result = call_llm_via_litellm(
        provider="efficiency",
        model="cheap-model",
        api_key="key",
        system_prompt="sys",
        user_message="hello",
        base_url="https://eff.example/v1",
        max_output_tokens=123,
        timeout=9,
    )

    assert result == "ok"
    assert captured["model"] == "openai/cheap-model"
    assert captured["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]
    assert captured["api_key"] == "key"
    assert captured["base_url"] == "https://eff.example/v1"
    assert captured["max_tokens"] == 123
    assert captured["timeout"] == 9


def test_call_llm_via_litellm_rejects_empty_response(monkeypatch):
    from integrations.llm_adapter import call_llm_via_litellm

    fake_litellm = ModuleType("litellm")
    fake_litellm.completion = lambda **_kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=""))],
        usage=SimpleNamespace(),
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    with pytest.raises(RuntimeError, match="empty response"):
        call_llm_via_litellm(
            provider="gemini",
            model="gemini-3.1-flash-lite-preview",
            api_key="key",
            system_prompt="sys",
            user_message="hello",
        )
