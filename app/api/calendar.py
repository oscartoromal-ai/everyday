from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter

from app.api.schemas import (
    BlockIn,
    BlockMove,
    BlockOut,
    CalendarBlockOut,
    CalendarOut,
    EventIn,
    EventOut,
    EventPatch,
)
from app.db import DbSession
from app.models import Block, BlockState
from app.services import blocks as blocks_svc
from app.services import events as events_svc

router = APIRouter(prefix="/api", tags=["calendar"])


def _calendar_block(block: Block) -> CalendarBlockOut:
    return CalendarBlockOut(
        **BlockOut.model_validate(block).model_dump(), task_title=block.task.title
    )


@router.get("/calendar")
def calendar(start: datetime, end: datetime, db: DbSession) -> CalendarOut:
    """The calendar grid's data. Missed blocks from today render as faded ghost
    outlines; missed blocks from earlier days are gone (the past stays honest)."""
    events, raw_blocks = events_svc.calendar_range(db, start, end)
    today = date.today()
    blocks: list[CalendarBlockOut] = []
    ghosts: list[CalendarBlockOut] = []
    for block in raw_blocks:
        if block.state == BlockState.missed:
            if block.start.date() == today:
                ghosts.append(_calendar_block(block))
        else:
            blocks.append(_calendar_block(block))
    return CalendarOut(
        events=[EventOut.model_validate(e) for e in events],
        blocks=blocks,
        ghosts=ghosts,
    )


@router.post("/blocks", status_code=201)
def schedule_block(body: BlockIn, db: DbSession) -> BlockOut:
    return BlockOut.model_validate(blocks_svc.schedule_block(db, **body.model_dump()))


@router.patch("/blocks/{block_id}")
def move_block(block_id: int, body: BlockMove, db: DbSession) -> BlockOut:
    return BlockOut.model_validate(blocks_svc.move_block(db, block_id, **body.model_dump()))


@router.post("/blocks/{block_id}/complete")
def complete_block(block_id: int, db: DbSession) -> BlockOut:
    return BlockOut.model_validate(blocks_svc.complete_block(db, block_id))


@router.delete("/blocks/{block_id}", status_code=204)
def delete_block(block_id: int, db: DbSession) -> None:
    blocks_svc.delete_block(db, block_id)


@router.post("/events", status_code=201)
def create_event(body: EventIn, db: DbSession) -> EventOut:
    return EventOut.model_validate(events_svc.create_event(db, **body.model_dump()))


@router.patch("/events/{event_id}")
def update_event(event_id: int, body: EventPatch, db: DbSession) -> EventOut:
    return EventOut.model_validate(
        events_svc.update_event(db, event_id, **body.model_dump(exclude_unset=True))
    )


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: DbSession) -> None:
    events_svc.delete_event(db, event_id)
