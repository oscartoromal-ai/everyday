"""The notebook: one page per day, written like a document.

A page is its blocks, in the order they were written:

    {"kind": "text", "text": "Slow morning.\\nCalled Ana."}   prose, as written
    {"kind": "task", "id": 42}                              a task, by reference
    {"kind": "reflection", "text": "..."}                   a reflection, free text

Tasks are only referenced: the page shows each as it stands now, wherever it
was changed since, and a task deleted since shows as its last known title.
A task written on a page carries that day in `written_on`; one whose
reference never reached the page (a save lost to a closed tab) still shows
on it, after what was written.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NotebookPage, Task, TaskRevision
from app.services import DomainError


class StalePage(DomainError):
    """The page was saved elsewhere since this copy was read."""


KINDS = ("text", "task", "reflection")


def get_page(db: Session, day: date) -> NotebookPage | None:
    return db.scalars(select(NotebookPage).where(NotebookPage.day == day)).first()


def _clean_text(text: Any) -> str:
    if not isinstance(text, str):
        raise DomainError("A text block's text must be a string")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _known_task_ids(db: Session, ids: set[int]) -> set[int]:
    """Ids that are, or once were, tasks."""
    if not ids:
        return set()
    live = set(db.scalars(select(Task.id).where(Task.id.in_(ids))))
    gone = set(db.scalars(select(TaskRevision.task_id).where(TaskRevision.task_id.in_(ids))))
    return live | gone


def _links(block: dict[str, Any]) -> dict[Any, Any]:
    links = block.get("links") or {}
    if not isinstance(links, dict):
        raise DomainError("A text block's links map its rows to tasks")
    return links


def normalize(db: Session, blocks: Any) -> list[dict[str, Any]]:
    """Blocks as the page stores them: known shapes only, prose as written
    (blank lines kept between other blocks, not at the page's top or
    bottom), reflections without blank edges, adjacent prose joined, each
    task once.

    A text block may carry `links`, {row: task id}, naming the rows that
    are tasks (the notepad's "- [ ] " rows); they follow the text as the
    page's blank top lines are trimmed, and only known tasks are kept."""
    if not isinstance(blocks, list):
        raise DomainError("A page is a list of blocks")
    task_ids = {
        b.get("id") for b in blocks if isinstance(b, dict) and b.get("kind") == "task"
    }
    for b in blocks:
        if isinstance(b, dict) and b.get("kind") == "text":
            task_ids |= set(_links(b).values())
    known = _known_task_ids(db, {i for i in task_ids if isinstance(i, int)})
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("kind") not in KINDS:
            raise DomainError(f"Unknown block: {block!r}")
        kind = block["kind"]
        if kind == "task":
            task_id = block.get("id")
            if task_id in known and task_id not in seen:
                seen.add(task_id)
                out.append({"kind": "task", "id": task_id})
            continue
        # A reflection is its words, without blank lines around them. Prose
        # keeps its blank lines (the notes' spacing, around a reflection
        # too), except at the page's top and bottom.
        lines = _clean_text(block.get("text", "")).split("\n")
        edges = kind == "reflection"
        lead = 0
        if edges or not out:
            while lead < len(lines) and not lines[lead].strip():
                lead += 1
        end = len(lines)
        if edges or index == len(blocks) - 1:
            while end > lead and not lines[end - 1].strip():
                end -= 1
        text = "\n".join(lines[lead:end])
        if not text.strip() and (edges or not out or index == len(blocks) - 1):
            continue
        links: dict[int, int] = {}
        if kind == "text":
            for row, task_id in _links(block).items():
                try:
                    at = int(row) - lead
                except (TypeError, ValueError) as exc:
                    raise DomainError(f"Not a row: {row!r}") from exc
                if task_id in known and 0 <= at < end - lead:
                    links[at] = task_id
        if kind == "text" and out and out[-1]["kind"] == "text":
            shift = out[-1]["text"].count("\n") + 1
            out[-1]["text"] += "\n" + text
            merged = {int(r): t for r, t in out[-1].get("links", {}).items()}
            merged |= {r + shift: t for r, t in links.items()}
            if merged:
                out[-1]["links"] = {str(r): t for r, t in sorted(merged.items())}
        else:
            out.append({"kind": kind, "text": text})
            if links:
                out[-1]["links"] = {str(r): t for r, t in sorted(links.items())}
    return out


def save_page(
    db: Session, day: date, blocks: Any, *, version: int
) -> NotebookPage:
    """Replace the day's page with `blocks`, if `version` is the page's
    current one (0 for a page not yet written)."""
    page = get_page(db, day)
    current = page.version if page else 0
    if version != current:
        raise StalePage("This page was changed in another window.")
    if page is None:
        page = NotebookPage(day=day, blocks=[], version=0)
        db.add(page)
    page.blocks = normalize(db, blocks)
    page.version = current + 1
    page.updated_at = datetime.now()
    db.flush()
    return page


def blocks_of(db: Session, day: date) -> list[dict[str, Any]]:
    """The day's blocks as they read now: every task resolved (None when it
    was deleted, with its last known snapshot), and any task written on the
    day but missing from the page appended after what was written."""
    page = get_page(db, day)
    stored = list(page.blocks) if page else []
    ids = [b["id"] for b in stored if b["kind"] == "task"]
    stray = db.scalars(
        select(Task).where(Task.written_on == day, Task.id.notin_(ids)).order_by(Task.created_at)
    )
    stored += [{"kind": "task", "id": t.id} for t in stray]
    ids = [b["id"] for b in stored if b["kind"] == "task"]
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_(ids)))}
    from app.services.history import last_known

    gone = last_known(db, [i for i in ids if i not in tasks])
    out: list[dict[str, Any]] = []
    for block in stored:
        if block["kind"] == "task":
            task = tasks.get(block["id"])
            out.append({
                "kind": "task",
                "id": block["id"],
                "task": task,
                "last_known": None if task else gone.get(block["id"], {}),
            })
        else:
            out.append(dict(block))
    return out


def task_ids_on(db: Session, day: date) -> set[int]:
    """Tasks the day's page holds (written there, or referenced by it)."""
    return {b["id"] for b in blocks_of(db, day) if b["kind"] == "task"}


def version_of(db: Session, day: date) -> int:
    page = get_page(db, day)
    return page.version if page else 0
