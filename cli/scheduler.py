"""轻量 cron 调度器 — TUI 定时触发 Agent 任务。"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEDULES_PATH = Path.home() / ".wyckoff" / "schedules.json"

DEFAULT_PRESETS: list[dict] = [
    {
        "id": "mkt-open",
        "name": "盘前风控检查",
        "cron": "25 9 * * 1-5",
        "action": "/checkup",
        "notify": True,
        "enabled": False,
    },
    {
        "id": "eod-review",
        "name": "收盘复盘",
        "cron": "5 15 * * 1-5",
        "action": "大盘水温怎么样？持仓做个体检，给我今天的总结和明天的策略建议",
        "notify": True,
        "enabled": False,
    },
]


@dataclass
class Schedule:
    id: str
    name: str
    cron: str
    action: str
    notify: bool = True
    enabled: bool = True
    last_fired: str = ""


def load_schedules() -> list[Schedule]:
    if not SCHEDULES_PATH.exists():
        schedules = [Schedule(**p) for p in DEFAULT_PRESETS]
        save_schedules(schedules)
        return schedules
    try:
        raw = json.loads(SCHEDULES_PATH.read_text(encoding="utf-8"))
        return [Schedule(**s) for s in raw]
    except Exception:
        logger.warning("Failed to load schedules, using defaults")
        return [Schedule(**p) for p in DEFAULT_PRESETS]


def save_schedules(schedules: list[Schedule]) -> None:
    SCHEDULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_PATH.write_text(
        json.dumps([asdict(s) for s in schedules], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cron_matches_now(cron: str, at: datetime | None = None) -> bool:
    now = at or datetime.now()
    fields = cron.strip().split()
    if len(fields) != 5:
        return False
    checks = [
        (fields[0], now.minute, 0, 59),
        (fields[1], now.hour, 0, 23),
        (fields[2], now.day, 1, 31),
        (fields[3], now.month, 1, 12),
        (fields[4], now.isoweekday() % 7, 0, 6),
    ]
    return all(_field_matches(pat, val, lo, hi) for pat, val, lo, hi in checks)


def _field_matches(pattern: str, value: int, lo: int, hi: int) -> bool:
    if pattern == "*":
        return True
    for part in pattern.split(","):
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            start = lo if base == "*" else int(base)
            if step > 0 and value >= start and (value - start) % step == 0:
                return True
        elif "-" in part:
            a, b = part.split("-", 1)
            if int(a) <= value <= int(b):
                return True
        elif value == int(part):
            return True
    return False
