"""A chat with Claude as a page draws it (Nutrition's, Spending's): its
messages, and the answer still being written, if one is."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from markupsafe import Markup, escape

from app.markdown import render_markdown
from app.models import ChatRole
from app.services.agent_chat import Run


class Message(Protocol):
    role: ChatRole
    text: str
    failed: bool
    created_at: datetime


def message_html(text: str, role: ChatRole) -> Markup:
    if role == ChatRole.claude:
        return Markup(render_markdown(text))
    # Oscar's words as he wrote them, his line breaks kept.
    lines = Markup("<br>").join(escape(line) for line in text.splitlines())
    return Markup("<p>") + lines + Markup("</p>")


def chat_ctx(messages: Iterable[Message], run: Run | None) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": m.role.value, "time": m.created_at.strftime("%H:%M"), "failed": m.failed,
                "html": message_html(m.text, m.role),
            }
            for m in messages
        ],
        "pending": run.pending() if run is not None else None,
    }
