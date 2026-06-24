"""Orchestrate configured notification channels."""

from __future__ import annotations

import utils.markdown_webhooks
import utils.telegram
from utils.feishu import send_feishu_notification


def send_all_webhooks(
    feishu_url: str,
    wecom_url: str,
    dingtalk_url: str,
    title: str,
    content: str,
    *,
    tg_bot_token: str = "",
    tg_chat_id: str = "",
) -> None:
    for label, sender, args, kwargs in _channel_calls(
        feishu_url,
        wecom_url,
        dingtalk_url,
        title,
        content,
        tg_bot_token=tg_bot_token,
        tg_chat_id=tg_chat_id,
    ):
        try:
            sender(*args, **kwargs)
        except Exception as exc:
            if _channel_configured(label, args, kwargs):
                print(f"[notify] {label} failed: {exc}")


def _channel_calls(
    feishu_url: str,
    wecom_url: str,
    dingtalk_url: str,
    title: str,
    content: str,
    *,
    tg_bot_token: str,
    tg_chat_id: str,
) -> list[tuple[str, object, tuple, dict]]:
    tg_content = f"{title}\n\n{content}" if title else content
    return [
        ("feishu", send_feishu_notification, (feishu_url, title, content), {}),
        ("wecom", utils.markdown_webhooks.send_wecom_notification, (wecom_url, title, content), {}),
        ("dingtalk", utils.markdown_webhooks.send_dingtalk_notification, (dingtalk_url, title, content), {}),
        (
            "telegram",
            utils.telegram.send_to_telegram,
            (tg_content,),
            {"tg_bot_token": tg_bot_token, "tg_chat_id": tg_chat_id},
        ),
    ]


def _channel_configured(label: str, args: tuple, kwargs: dict) -> bool:
    if label == "telegram":
        return bool(kwargs.get("tg_bot_token") and kwargs.get("tg_chat_id"))
    return bool(args[0])
