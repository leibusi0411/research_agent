from __future__ import annotations

import secrets
import re
from datetime import datetime, timezone


TASK_ID_PATTERN = re.compile(r"^task_\d{8}_\d{6}_[a-f0-9]{6}$")


def utc_now_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    current = current.astimezone(timezone.utc).replace(microsecond=0)
    return current.isoformat().replace("+00:00", "Z")


def generate_task_id(now: datetime | None = None, suffix: str | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    current = current.astimezone(timezone.utc)
    random_suffix = suffix or secrets.token_hex(3)
    task_id = f"task_{current:%Y%m%d_%H%M%S}_{random_suffix}"
    validate_task_id(task_id)
    return task_id


def validate_task_id(task_id: str) -> None:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError(f"invalid task_id: {task_id}")
