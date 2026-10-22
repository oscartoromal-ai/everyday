"""The work seen in herdr, recorded (SPEC.md, Work in herdr): a day's, a
line for each thing worked on, and a terminal filed under a task."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from app.api.schemas import WorkDayOut, WorkFileIn, WorkLineOut, WorkSessionOut
from app.db import DbSession
from app.services import work_log

router = APIRouter(prefix="/api/work", tags=["work"])


@router.get("")
def work_day(db: DbSession, day: date | None = None) -> WorkDayOut:
    """The day's work (today's unless given), the most of Oscar's time
    first: each task, project or unfiled terminal, with the seconds Oscar
    was at it, its agents worked, and they waited on him."""
    on = day or date.today()
    return WorkDayOut(
        day=on,
        lines=[
            WorkLineOut(
                task_id=line.task.id if line.task else None,
                project_id=line.task.project_id if line.task else (
                    line.project.id if line.project else None
                ),
                session_id=line.session.id if line.session else None,
                you_seconds=round(line.totals.you),
                working_seconds=round(line.totals.working),
                blocked_seconds=round(line.totals.blocked),
                sessions=len(line.sessions),
            )
            for line in work_log.day(db, on)
        ],
    )


@router.patch("/sessions/{session_id}")
def file_session(session_id: int, body: WorkFileIn, db: DbSession) -> WorkSessionOut:
    """A terminal filed under a task (null: under none); it stays so."""
    return WorkSessionOut.model_validate(work_log.file(db, session_id, body.task_id))
