"""Block domain logic: scheduling, completion, the missed transition, ghosts."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Block, BlockState, Task, TaskStatus
from app.services import DomainError


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
    db.delete(block)
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
