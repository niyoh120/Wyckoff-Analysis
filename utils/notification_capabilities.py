"""Channel limits and safe text splitting for notification delivery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationCapabilities:
    channel: str
    markdown: bool
    max_bytes: int
    supports_cards: bool = False
    supports_files: bool = False


CHANNEL_CAPABILITIES = {
    "feishu": NotificationCapabilities(
        "feishu", markdown=True, max_bytes=11_000, supports_cards=True, supports_files=True
    ),
    "wecom": NotificationCapabilities("wecom", markdown=True, max_bytes=4_000),
    "dingtalk": NotificationCapabilities("dingtalk", markdown=True, max_bytes=4_000),
    "telegram": NotificationCapabilities("telegram", markdown=True, max_bytes=4_096),
}


def notification_capabilities(channel: str) -> NotificationCapabilities:
    """Return a conservative capability profile for a configured channel."""
    return CHANNEL_CAPABILITIES.get(channel, NotificationCapabilities(channel, markdown=False, max_bytes=2_000))


def split_utf8_text(text: str, max_bytes: int) -> list[str]:
    """Split text on paragraph/line boundaries while staying inside a byte limit."""
    raw = str(text or "")
    limit = max(int(max_bytes), 1)
    if len(raw.encode("utf-8")) <= limit:
        return [raw]

    chunks: list[str] = []
    current = ""
    for piece in _text_pieces(raw):
        candidate = f"{current}{piece}"
        if current and len(candidate.encode("utf-8")) > limit:
            chunks.append(current.rstrip())
            current = ""
        if len(piece.encode("utf-8")) <= limit:
            current += piece
            continue
        if current:
            chunks.append(current.rstrip())
            current = ""
        chunks.extend(_split_long_piece(piece, limit))
    if current:
        chunks.append(current.rstrip())
    return [chunk for chunk in chunks if chunk]


def _text_pieces(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    return lines or [text]


def _split_long_piece(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for char in text:
        if current and len((current + char).encode("utf-8")) > limit:
            chunks.append(current)
            current = char
        else:
            current += char
    if current:
        chunks.append(current)
    return chunks


__all__ = ["CHANNEL_CAPABILITIES", "NotificationCapabilities", "notification_capabilities", "split_utf8_text"]
