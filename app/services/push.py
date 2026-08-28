"""Phone push via managed ntfy.sh (SPEC.md section 8).

Topic and token live in git-ignored files under local/. Quiet hours suppress
break-through pushes; the morning digest is scheduled outside them.
"""

from __future__ import annotations

import logging
from datetime import datetime, time

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


def _read_local(path_str: str) -> str | None:
    from pathlib import Path

    from app.config import REPO_ROOT

    path = Path(path_str)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def in_quiet_hours(now: datetime) -> bool:
    settings = get_settings()
    start_s, end_s = settings.push.quiet_hours
    start = time.fromisoformat(start_s)
    end = time.fromisoformat(end_s)
    current = now.time()
    if start <= end:
        return start <= current < end
    return current >= start or current < end  # window wraps midnight


def send_push(title: str, message: str) -> bool:
    """POST to ntfy; returns False (and logs) when unconfigured or failing."""
    settings = get_settings()
    topic = _read_local(settings.push.ntfy_topic_file)
    if not topic:
        log.info("Push skipped: no ntfy topic configured")
        return False
    token = _read_local(settings.push.ntfy_token_file)
    headers = {"Title": title}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.post(
            f"{settings.push.ntfy_server}/{topic}",
            content=message.encode("utf-8"),
            headers=headers,
            timeout=10.0,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        log.exception("Push to ntfy failed")
        return False
