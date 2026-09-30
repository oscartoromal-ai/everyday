"""Nutrition's chat: a day's messages, and Claude's answer running on.

Oscar's message is saved, then Claude answers it on a thread of its own,
so the run goes on (and its answer is saved) even when the page that asked
is closed. The page follows a run's events as they come: the answer's words
and what Claude is doing meanwhile. One run at a time per day.

After a run, the day's log is read back; if it cannot be read, Claude gets
one turn, unseen, to fix it.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import NutritionMessage, NutritionRole
from app.services import DomainError
from app.services import nutrition as nutrition_svc
from app.services.nutrition_agent import Agent, AgentFailed, AgentRequest

log = logging.getLogger(__name__)

# A run longer than this is cut short, its answer saved as far as it got.
RUN_TIMEOUT_S = 300
# The longest message Oscar can send.
MAX_MESSAGE = 4000


class Run:
    """One answer being written: its events, in order, for any page that
    follows it, and whether it has finished."""

    def __init__(self, day: date) -> None:
        self.day = day
        self.events: list[dict[str, Any]] = []
        self.finished = False
        self._changed = threading.Condition()

    def emit(self, event: dict[str, Any]) -> None:
        with self._changed:
            self.events.append(event)
            self._changed.notify_all()

    def finish(self) -> None:
        with self._changed:
            self.finished = True
            self._changed.notify_all()

    def wait(self, seen: int, timeout: float) -> tuple[list[dict[str, Any]], bool]:
        """The events after the first `seen`, waiting up to `timeout` seconds
        for one, and whether the run has finished."""
        with self._changed:
            self._changed.wait_for(lambda: len(self.events) > seen or self.finished, timeout)
            return self.events[seen:], self.finished


_runs: dict[date, Run] = {}
_runs_lock = threading.Lock()


def running(day: date) -> Run | None:
    with _runs_lock:
        return _runs.get(day)


def messages(db: Session, day: date) -> list[NutritionMessage]:
    return list(db.scalars(
        select(NutritionMessage).where(NutritionMessage.day == day).order_by(NutritionMessage.id)
    ))


def start(
    db: Session, day: date, text: str, *, agent: Agent, profile: dict[str, Any],
    now: datetime | None = None,
) -> Run:
    """Save Oscar's message and set Claude answering it."""
    text = text.strip()
    if not text:
        raise DomainError("Write a message first")
    if len(text) > MAX_MESSAGE:
        raise DomainError(f"That message is too long: {MAX_MESSAGE} characters at most")
    run = Run(day)
    with _runs_lock:
        if day in _runs:
            raise DomainError("Claude is still answering the last message")
        _runs[day] = run
    try:
        transcript = [(m.role.value, m.text) for m in messages(db, day) if not m.failed]
        db.add(NutritionMessage(day=day, role=NutritionRole.oscar, text=text))
        db.commit()
    except Exception:
        with _runs_lock:
            _runs.pop(day, None)
        raise
    request = AgentRequest(
        day=day, now=now or datetime.now(), message=text,
        folder=get_settings().nutrition_dir, profile=profile, transcript=transcript,
    )
    # A session factory on the request's own database, for the thread.
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    threading.Thread(
        target=_work, args=(run, agent, request, factory), name=f"nutrition-{day}", daemon=True
    ).start()
    return run


def _work(run: Run, agent: Agent, request: AgentRequest, factory: sessionmaker[Session]) -> None:
    text, failed = "", False
    try:
        # Its own event loop: asyncio.run's default on Windows (Proactor)
        # can run the CLI as a subprocess whatever loop served the request.
        text = asyncio.run(_drive(run, agent, request))
    except AgentFailed as exc:
        failed, text = True, _with_reason(run, str(exc))
    except TimeoutError:
        failed, text = True, _with_reason(run, "Claude took too long, so the answer was cut short.")
    except Exception as exc:
        log.exception("Nutrition chat run failed")
        failed, text = True, _with_reason(run, f"Something went wrong: {exc}")
    try:
        with factory() as db:
            db.add(NutritionMessage(
                day=request.day, role=NutritionRole.claude, text=text, failed=failed
            ))
            db.commit()
    except Exception:
        log.exception("Could not save Claude's answer")
    finally:
        run.emit({"type": "done", "failed": failed})
        with _runs_lock:
            _runs.pop(request.day, None)
        run.finish()


def _said(run: Run) -> str:
    return "".join(e["text"] for e in run.events if e["type"] == "text").strip()


def _with_reason(run: Run, reason: str) -> str:
    said = _said(run)
    return f"{said}\n\n{reason}" if said else reason


async def _drive(run: Run, agent: Agent, request: AgentRequest) -> str:
    async with asyncio.timeout(RUN_TIMEOUT_S):
        async for event in agent(request):
            run.emit({"type": event.kind, "text": event.text})
        problem = _problem(request)
        if problem:
            run.emit({"type": "status", "text": "Fixing the day's log"})
            async for event in agent(replace(request, message=problem, transcript=[], repair=True)):
                if event.kind == "status":
                    run.emit({"type": "status", "text": event.text})
    return _said(run)


def _problem(request: AgentRequest) -> str | None:
    """Why the day's log cannot be read, or None when it can (or is not there)."""
    try:
        nutrition_svc.read_day(request.folder, request.day)
    except nutrition_svc.NutritionFileError as exc:
        return str(exc)
    return None
