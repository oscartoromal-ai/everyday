"""Spending's chat: a month's messages, and Claude's answer running on
(agent_chat). One run at a time per month."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ChatRole, MoneyMessage
from app.services import agent_chat
from app.services.agent_chat import Run
from app.services.money_agent import Agent, AgentRequest

runs = agent_chat.Runs()


def running(month: date) -> Run | None:
    return runs.running(month)


def messages(db: Session, month: date) -> list[MoneyMessage]:
    return list(db.scalars(
        select(MoneyMessage).where(MoneyMessage.month == month).order_by(MoneyMessage.id)
    ))


def start(db: Session, month: date, text: str, *, agent: Agent, now: datetime | None = None) -> Run:
    """Save Oscar's message and set Claude answering it."""
    text = agent_chat.check_message(text)
    run = runs.begin(month)
    try:
        transcript = [(m.role.value, m.text) for m in messages(db, month) if not m.failed]
        db.add(MoneyMessage(month=month, role=ChatRole.oscar, text=text))
        db.commit()
    except Exception:
        runs.end(month)
        raise
    # A session factory on the request's own database, for the thread and
    # Claude's tools.
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    request = AgentRequest(
        month=month, now=now or datetime.now(), message=text, factory=factory,
        transcript=transcript,
    )

    async def drive(run: Run) -> None:
        async for event in agent(request):
            run.emit({"type": event.kind, "text": event.text})

    def save(answer: str, failed: bool) -> None:
        with factory() as session:
            session.add(MoneyMessage(month=month, role=ChatRole.claude, text=answer, failed=failed))
            session.commit()

    agent_chat.answer(runs, run, drive, save, name=f"money-{month:%Y-%m}")
    return run
