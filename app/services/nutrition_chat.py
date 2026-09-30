"""Nutrition's chat: a day's messages, and Claude's answer running on
(agent_chat). One run at a time per day.

After a run, the day's log is read back; if it cannot be read, Claude gets
one turn, unseen, to fix it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import ChatRole, NutritionMessage
from app.services import agent_chat
from app.services import nutrition as nutrition_svc
from app.services.agent_chat import Run
from app.services.nutrition_agent import Agent, AgentRequest

runs = agent_chat.Runs()


def running(day: date) -> Run | None:
    return runs.running(day)


def messages(db: Session, day: date) -> list[NutritionMessage]:
    return list(db.scalars(
        select(NutritionMessage).where(NutritionMessage.day == day).order_by(NutritionMessage.id)
    ))


def start(
    db: Session, day: date, text: str, *, agent: Agent, profile: dict[str, Any],
    garmin: list[dict[str, Any]] | None = None, now: datetime | None = None,
) -> Run:
    """Save Oscar's message and set Claude answering it. `garmin` is what his
    watch measured on the day and the day before (garmin.report)."""
    text = agent_chat.check_message(text)
    run = runs.begin(day)
    try:
        transcript = [(m.role.value, m.text) for m in messages(db, day) if not m.failed]
        db.add(NutritionMessage(day=day, role=ChatRole.oscar, text=text))
        db.commit()
    except Exception:
        runs.end(day)
        raise
    request = AgentRequest(
        day=day, now=now or datetime.now(), message=text,
        folder=get_settings().nutrition_dir, profile=profile, transcript=transcript,
        garmin=garmin or [],
    )
    # A session factory on the request's own database, for the thread.
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    async def drive(run: Run) -> None:
        async for event in agent(request):
            run.emit({"type": event.kind, "text": event.text})
        problem = _problem(request)
        if problem:
            run.emit({"type": "status", "text": "Fixing the day's log"})
            async for event in agent(replace(request, message=problem, transcript=[], repair=True)):
                if event.kind == "status":
                    run.emit({"type": "status", "text": event.text})

    def save(answer: str, failed: bool) -> None:
        with factory() as session:
            session.add(NutritionMessage(day=day, role=ChatRole.claude, text=answer, failed=failed))
            session.commit()

    agent_chat.answer(runs, run, drive, save, name=f"nutrition-{day}")
    return run


def _problem(request: AgentRequest) -> str | None:
    """Why the day's log cannot be read, or None when it can (or is not there)."""
    try:
        nutrition_svc.read_day(request.folder, request.day)
    except nutrition_svc.NutritionFileError as exc:
        return str(exc)
    return None
