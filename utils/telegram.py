"""Telegram Bot delivery helpers."""

from __future__ import annotations

import os

import requests

from integrations.tickflow_notice import append_tickflow_limit_hint

TELEGRAM_MAX_LEN = 3900


def split_telegram_message(content: str, max_len: int = TELEGRAM_MAX_LEN) -> list[str]:
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    current = ""
    for line in content.splitlines(keepends=True):
        if len(line) > max_len:
            _append_long_line_chunks(chunks, current, line, max_len)
            current = ""
            continue
        if len(current) + len(line) <= max_len:
            current += line
            continue
        if current:
            chunks.append(current.rstrip("\n"))
        current = line
    if current:
        chunks.append(current.rstrip("\n"))
    return chunks


def _append_long_line_chunks(chunks: list[str], current: str, line: str, max_len: int) -> None:
    if current:
        chunks.append(current.rstrip("\n"))
    start = 0
    while start < len(line):
        chunks.append(line[start : start + max_len].rstrip("\n"))
        start += max_len


def _telegram_proxies() -> dict[str, str] | None:
    proxy_url = os.getenv("PROXY_URL", "").strip()
    return {"http": proxy_url, "https": proxy_url} if proxy_url else None


def _telegram_payload(chat_id: str, chunk: str, idx: int, total: int) -> dict:
    return {
        "chat_id": chat_id,
        "text": chunk if total == 1 else f"[{idx}/{total}]\n{chunk}",
        "disable_web_page_preview": True,
    }


def send_to_telegram(message_text: str, *, tg_bot_token: str, tg_chat_id: str) -> bool:
    token = str(tg_bot_token or "").strip()
    chat_id = str(tg_chat_id or "").strip()
    message_text = append_tickflow_limit_hint(message_text)
    if not token or not chat_id:
        print("[telegram] tg_bot_token/tg_chat_id 未配置，跳过 Telegram 推送")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = split_telegram_message(message_text)
    proxies = _telegram_proxies()
    for idx, chunk in enumerate(chunks, start=1):
        if not _post_telegram_chunk(url, _telegram_payload(chat_id, chunk, idx, len(chunks)), proxies):
            return False
    return True


def _post_telegram_chunk(url: str, payload: dict, proxies: dict[str, str] | None) -> bool:
    try:
        resp = requests.post(url, json=payload, timeout=15, proxies=proxies)
        if resp.status_code == 200:
            return True
        print(f"[telegram] 推送失败: status={resp.status_code}, body={resp.text[:200]}")
        return False
    except Exception as e:
        print(f"[telegram] 推送异常: {e}")
        return False
