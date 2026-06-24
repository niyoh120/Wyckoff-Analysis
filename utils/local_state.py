from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|token|password|secret|authorization|cookie)", re.IGNORECASE)
_MAX_INLINE_STRING = 200_000


def wyckoff_home() -> Path:
    return Path(os.getenv("WYCKOFF_HOME", Path.home() / ".wyckoff")).expanduser()


def scrub_sensitive_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            cleaned[key_text] = "***REDACTED***" if _SENSITIVE_KEY_RE.search(key_text) else scrub_sensitive_value(item)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [scrub_sensitive_value(item) for item in value]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > _MAX_INLINE_STRING:
            return value[:_MAX_INLINE_STRING] + f"\n...[truncated in scratchpad, original chars={len(value)}]"
        return value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
