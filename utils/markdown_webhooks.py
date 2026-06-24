"""Enterprise markdown webhook delivery for WeCom and DingTalk."""

from __future__ import annotations

import requests

from integrations.tickflow_notice import append_tickflow_limit_hint

MARKDOWN_MAX_BYTES = 4000


def _markdown_body(title: str, content: str) -> str:
    content = append_tickflow_limit_hint(content)
    body = f"# {title}\n\n{content}" if title else content
    if len(body.encode("utf-8")) > MARKDOWN_MAX_BYTES:
        return body[: MARKDOWN_MAX_BYTES // 2] + "\n\n...(内容过长已截断)"
    return body


def _webhook_payload(tag: str, title: str, body: str) -> dict:
    if tag == "dingtalk":
        return {"msgtype": "markdown", "markdown": {"title": title or "通知", "text": body}}
    return {"msgtype": "markdown", "markdown": {"content": body}}


def _send_webhook_markdown(tag: str, webhook_url: str, title: str, content: str) -> bool:
    url = str(webhook_url or "").strip()
    if not url:
        return False
    try:
        resp = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=_webhook_payload(tag, title, _markdown_body(title, content)),
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[{tag}] http {resp.status_code}: {resp.text[:200]}")
            return False
        data = resp.json()
        if data.get("errcode") == 0:
            return True
        print(f"[{tag}] errcode {data.get('errcode')}: {data.get('errmsg', '')}")
        return False
    except Exception as e:
        print(f"[{tag}] exception: {e}")
        return False


def send_wecom_notification(webhook_url: str, title: str, content: str) -> bool:
    return _send_webhook_markdown("wecom", webhook_url, title, content)


def send_dingtalk_notification(webhook_url: str, title: str, content: str) -> bool:
    return _send_webhook_markdown("dingtalk", webhook_url, title, content)
