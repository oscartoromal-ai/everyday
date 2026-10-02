"""Block domain logic: scheduling, completion, the missed transition, ghosts."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Block, BlockState, Event, Task, TaskStatus
from app.services import DomainError

# Time given without an end: what a drop on the timeline gives (calendar.js
# DEFAULT_BLOCK_MIN) and the keyboard's B.
DEFAULT_LENGTH = timedelta(hours=1)


def schedule_block(db: Session, *, task_id: int, start: datetime, end: datetime) -> Block:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError(f"Task {task_id} does not exist")
    if task.status in (TaskStatus.done, TaskStatus.cancelled):
        raise DomainError("Cannot schedule a block for a closed task")
    if end <= start:
        raise DomainError("A block must end after it starts")
    # Assigning via the relationship keeps an already-loaded task.blocks in sync.
    block = Block(task=task, start=start, end=end)
    db.add(block)
    db.flush()
    return block


def next_free_slot(
    db: Session, *, duration: timedelta, after: datetime, until: datetime, step_minutes: int = 15
) -> datetime | None:
    """The earliest start at or after `after`, on a quarter-hour boundary, where
    `duration` fits before `until` without overlapping a timed event or another
    planned or completed block. All-day events, cancelled meetings and missed
    blocks take no time."""
    events = db.scalars(
        select(Event).where(Event.start < until, Event.end > after, Event.all_day.is_(False))
    )
    blocks = db.scalars(
        select(Block).where(
            Block.start < until, Block.end > after, Block.state != BlockState.missed
        )
    )
    busy = sorted(
        [(e.start, e.end) for e in events if not e.cancelled] + [(b.start, b.end) for b in blocks]
    )
    step = timedelta(minutes=step_minutes)

    def on_step(moment: datetime) -> datetime:
        floor = moment.replace(minute=0, second=0, microsecond=0)
        steps = -(-(moment - floor) // step)  # ceiling division
        return floor + steps * step

    start = on_step(after)
    while start + duration <= until:
        end = start + duration
        clash = next(((s, e) for s, e in busy if s < end and e > start), None)
        if clash is None:
            return start
        start = on_step(max(clash[1], start + step))
    return None


def move_block(db: Session, block_id: int, *, start: datetime, end: datetime) -> Block:
    block = get_block(db, block_id)
    if block.state != BlockState.planned:
        raise DomainError("Only planned blocks can be moved")
    if end <= start:
        raise DomainError("A block must end after it starts")
    block.start = start
    block.end = end
    db.flush()
    return block


def complete_block(db: Session, block_id: int) -> Block:
    """Mark a block completed. Also completes missed blocks worked after the fact."""
    block = get_block(db, block_id)
    block.state = BlockState.completed
    db.flush()
    return block


def delete_block(db: Session, block_id: int) -> None:
    block = get_block(db, block_id)
    # Leaving the task's blocks deletes it (delete-orphan), and keeps the task's
    # loaded collection true for the rest of the session.
    block.task.blocks.remove(block)
    db.flush()


def get_block(db: Session, block_id: int) -> Block:
    block = db.get(Block, block_id)
    if block is None:
        raise DomainError(f"Block {block_id} does not exist")
    return block


def mark_missed_blocks(db: Session, now: datetime) -> list[Block]:
    """The periodic job body: planned blocks whose end has passed become missed."""
    stmt = select(Block).where(Block.state == BlockState.planned, Block.end < now)
    missed = list(db.scalars(stmt))
    for block in missed:
        block.state = BlockState.missed
    db.flush()
    return missed


def ghost_blocks(db: Session, day: date) -> list[Block]:
    """Missed blocks that started on `day`; today they render as faded ghost
    outlines on the calendar, and by construction they are gone tomorrow."""
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    stmt = select(Block).where(
        Block.state == BlockState.missed,
        Block.start >= day_start,
        Block.start < day_end,
    )
    return list(db.scalars(stmt))


def day_block(task: Task, day: date) -> Block | None:
    """The task's time on `day`: its first planned block that starts then."""
    planned = [
        b for b in task.blocks if b.state == BlockState.planned and b.start.date() == day
    ]
    return min(planned, key=lambda b: b.start) if planned else None


def set_day_time(
    db: Session,
    task: Task,
    day: date,
    start: time | None,
    end: time | None,
    *,
    was: date | None = None,
) -> Block | None:
    """Give the task time on `day` from `start` to `end` (an hour, without
    one), moving the time it had on `was` (its day before a change of day;
    `day` itself by default); with no `start`, take that time away."""
    block = day_block(task, was or day)
    if start is None:
        if block is not None:
            delete_block(db, block.id)
        return None
    begin = datetime.combine(day, start)
    finish = datetime.combine(day, end) if end is not None else begin + DEFAULT_LENGTH
    if block is None:
        return schedule_block(db, task_id=task.id, start=begin, end=finish)
    return move_block(db, block.id, start=begin, end=finish)
