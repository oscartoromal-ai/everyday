"""The agent window as every page draws it: which agent, the model it runs on
(Models' choice), which agents are here to chat with, and the latest chat."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup
from sqlalchemy.orm import Session

from app.markdown import render_inline
from app.models import AgentKind
from app.services import agent_window as window_svc
from app.services import llm as llm_svc
from app.services.agents import LABELS, PROVIDERS, USES
from app.sources.llm import Status
from app.ui import chat_view

EMPTY = {
    AgentKind.claude: "Ask Claude anything. It answers from what it knows and the web; "
    "it cannot see your planner yet.",
    AgentKind.codex: "Ask Codex anything. It answers from what it knows; "
    "it cannot see your planner yet.",
}

# Why an agent is not here, in a word or two (Models' own words).
BADGES = {"signed_out": "Not signed in", "missing": "Not installed", "failed": "Needs attention"}


def why(kind: AgentKind, found: Status) -> str:
    """What is missing, and how to put it right, in Markdown; the window
    links to Models after it, where its CLI can be pointed to."""
    provider = PROVIDERS[kind]
    if found.state == "signed_out":
        return f"{provider.program} is not signed in here: run `{provider.sign_in}`."
    if found.state == "missing":
        return (
            f"{provider.program} is not installed here: install it (`{provider.install}`) "
            f"and sign in (`{provider.sign_in}`), or say where it is on Models."
        )
    return found.message or f"{provider.program} did not answer."


def model_name(db: Session, kind: AgentKind, found: Status | None) -> str:
    """The model the agent runs on, by its name, and its effort when chosen
    ("Claude Opus 5.5 · High"); the provider's default when none is."""
    choice = llm_svc.choice(db, USES[kind])
    if choice.model:
        listed = found.model(choice.model) if found else None
        name = listed.name if listed else choice.model
    else:
        default = found.default_model if found else None
        name = f"Default · {default.name}" if default else "Default model"
    if choice.effort:
        name += f" · {llm_svc.effort_label(choice.effort)}"
    return name


def window_ctx(db: Session) -> dict[str, Any]:
    conversation = window_svc.current(db)
    kind = conversation.agent if conversation is not None else window_svc.default_agent(db)
    known = {k: window_svc.status(db, k) for k in AgentKind}
    found = known[kind]
    ready = window_svc.here(found)
    name = LABELS[kind]
    chat = chat_view.chat_ctx(
        window_svc.messages(db, conversation), window_svc.running(conversation)
    )
    return {
        "conversation": conversation.id if conversation is not None else None,
        "agent": kind.value,
        "name": name,
        "model": model_name(db, kind, found),
        # The others say why they are not here in the list; the chosen one
        # says it under its name.
        "agents": [
            {
                "key": k.value,
                "label": LABELS[k],
                "badge": "" if k == kind or window_svc.here(s) else BADGES.get(s.state, ""),
            }
            for k, s in known.items()
        ],
        "ready": ready,
        "badge": "" if ready else BADGES.get(found.state, ""),
        "why": "" if ready else Markup(render_inline(why(kind, found))),
        "chat": {
            **chat,
            "name": name,
            "url": "/ui/agent/log",
            "log_id": "agent-log",
            "pending_id": "agent-pending",
            "empty": EMPTY[kind] if ready else "",
        },
    }
