"""Atomic file write helpers shared by integrations that cache JSON to disk."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

logger = logging.getLogger(__name__)


def atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON to `path` via a temp file + os.replace to avoid partial writes under concurrency."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_name = tmp.name
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except Exception:
                logger.debug("failed to remove temp file %s", tmp_name, exc_info=True)
