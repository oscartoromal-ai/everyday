"""The agent window's chats. The window shows the latest; New chat starts
another, and the ones before are kept. A chat is with one agent, so
choosing another once something is said starts a new chat with it.

Oscar's message is saved, then the agent answers it on a thread of its own
(agent_chat), so the answer goes on (and is saved) as he moves from page to
page. One run at a time per chat.

Whether an agent is here (its CLI installed and signed in) is Models' last
check of its provider (services/llm.py); one that was not is asked again
when Oscar turns to it, since he may have just installed it or signed in.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AgentConversation, AgentKind, AgentMessage, AgentRole
from app.services import DomainError, agent_chat
from app.services import llm as llm_svc
from app.services.agent_chat import Run
from app.services.agents import PROVIDERS, USES, Agent, AgentRequest
from app.sources.llm import Probe, Status

runs = agent_chat.Runs()


def running(conversation: AgentConversation | None) -> Run | None:
    return None if conversation is None else runs.running(conversation.id)


def status(db: Session, kind: AgentKind) -> Status | None:
    """The agent's provider as Models last checked it; None when never."""
    return llm_svc.status(db, PROVIDERS[kind].key)


def here(found: Status | None) -> bool:
    """Whether an agent can be asked: never checked counts, as a run says
    why when it cannot."""
    return found is None or found.state == "ready"


def recheck(db: Session, kind: AgentKind, probe: Probe) -> Status:
    """Ask the agent's provider again, now, and keep the answer for Models."""
    provider = PROVIDERS[kind].key
    found = probe(provider, llm_svc.cli(db, provider))
    llm_svc.keep(db, [found])
    db.commit()
    return found


def default_agent(db: Session) -> AgentKind:
    """The agent a first chat starts with: Claude, unless only Codex is here."""
    claude, codex = status(db, AgentKind.claude), status(db, AgentKind.codex)
    if not here(claude) and codex is not None and here(codex):
        return AgentKind.codex
    return AgentKind.claude


def current(db: Session) -> AgentConversation | None:
    """The chat the window shows: the latest."""
    return db.scalars(
        select(AgentConversation).order_by(AgentConversation.id.desc()).limit(1)
    ).first()


def messages(db: Session, conversation: AgentConversation | None) -> list[AgentMessage]:
    if conversation is None:
        return []
    return list(
        db.scalars(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
            .order_by(AgentMessage.id)
        )
    )


def new_chat(db: Session, agent: AgentKind) -> AgentConversation:
    """A fresh chat with `agent`; the latest is taken for it while nothing
    is said in it, so empty chats never pile up."""
    latest = current(db)
    if latest is None or messages(db, latest):
        latest = AgentConversation(agent=agent)
        db.add(latest)
    latest.agent = agent
    db.commit()
    return latest


def choose(db: Session, agent: AgentKind) -> AgentConversation:
    """The window's chat with `agent`: the latest, when it is with that
    agent; the one before it, when the latest is an empty one that the
    picker just left (Claude, Codex, and back to Claude finds Claude's chat
    as it was); else a new one."""
    latest = current(db)
    if latest is not None and latest.agent == agent:
        return latest
    if latest is not None and not messages(db, latest):
        before = db.scalars(
            select(AgentConversation)
            .where(AgentConversation.id < latest.id)
            .order_by(AgentConversation.id.desc())
            .limit(1)
        ).first()
        if before is not None and before.agent == agent:
            db.delete(latest)
            db.commit()
            return before
    return new_chat(db, agent)


def start(
    db: Session,
    conversation: AgentConversation,
    text: str,
    *,
    agent: Agent,
    now: datetime | None = None,
) -> Run:
    """Save Oscar's message and set the agent answering it."""
    text = agent_chat.check_message(text)
    run = runs.begin(conversation.id)
    try:
        transcript = [(m.role.value, m.text) for m in messages(db, conversation) if not m.failed]
        db.add(AgentMessage(conversation_id=conversation.id, role=AgentRole.oscar, text=text))
        db.commit()
    except Exception:
        runs.end(conversation.id)
        raise
    request = AgentRequest(
        now=now or datetime.now(),
        message=text,
        transcript=transcript,
        choice=llm_svc.choice(db, USES[conversation.agent]),
    )
    # A session factory on the request's own database, for the thread.
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    conversation_id = conversation.id

    async def drive(run: Run) -> None:
        async for event in agent(request):
            run.emit({"type": event.kind, "text": event.text})

    def save(answer: str, failed: bool) -> None:
        with factory() as session:
            session.add(
                AgentMessage(
                    conversation_id=conversation_id,
                    role=AgentRole.agent,
                    text=answer,
                    failed=failed,
                )
            )
            session.commit()

    agent_chat.answer(runs, run, drive, save, name=f"agent-{conversation_id}")
    return run


def get(db: Session, conversation_id: int) -> AgentConversation:
    conversation = db.get(AgentConversation, conversation_id)
    if conversation is None:
        raise DomainError("That chat is gone")
    return conversation
