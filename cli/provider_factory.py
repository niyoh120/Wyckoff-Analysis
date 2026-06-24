"""Provider 工厂函数 — 从 __main__ 抽出以消除循环导入。"""

from __future__ import annotations

from typing import Any


def provider_config_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_name": config["provider_name"],
        "api_key": config["api_key"],
        "model": config.get("model", ""),
        "base_url": config.get("base_url", ""),
        "context_window": config.get("context_window"),
    }


def create_provider(
    provider_name: str,
    api_key: str,
    model: str = "",
    base_url: str = "",
    context_window: int | None = None,
):
    import inspect

    from cli.providers import PROVIDERS

    cls = PROVIDERS.get(provider_name)
    if cls is None:
        install_hints = {
            "gemini": "pip install google-genai",
            "claude": "pip install anthropic",
            "openai": "pip install openai",
        }
        hint = install_hints.get(provider_name, "")
        return None, f"Provider '{provider_name}' 不可用，请先安装依赖：{hint}"

    kwargs = {"api_key": api_key}
    if model:
        kwargs["model"] = model
    if base_url:
        kwargs["base_url"] = base_url

    sig = inspect.signature(cls.__init__)
    kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}

    provider = cls(**kwargs)
    try:
        window = int(context_window or 0)
    except (TypeError, ValueError):
        window = 0
    if window > 0:
        provider.context_window = window
    return provider, None
