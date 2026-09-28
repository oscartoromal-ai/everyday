"""The notebook: one page per day, written like a document.

A page is its blocks, in the order they were written:

    {"kind": "text", "text": "Slow morning.\\nCalled Ana."}   prose, as written
    {"kind": "task", "id": 42}                              a task, by reference
    {"kind": "reflection", "text": "..."}                   a reflection, free text
    {"kind": "habit", "habit": 3, "done": true, "text": ""} a habit checked that day,
                                                            with a note (app.services.habits)
    {"kind": "stay", "text": "..."}                         where Oscar stays that day: a
                                                            note, then its items, each
                                                            "- [ ] name: value" (stay_items)

Tasks are only referenced: the page shows each as it stands now, wherever it
was changed since, and a task deleted since shows as its last known title.
A task written on a page carries that day in `written_on`; one whose
reference never reached the page (a save lost to a closed tab) still shows
on it, after what was written.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Habit, NotebookPage, Task, TaskRevision
from app.services import DomainError
from app.services import habits as habits_svc
from app.services import tasks as tasks_svc


class StalePage(DomainError):
    """The page was saved elsewhere since this copy was read."""


KINDS = ("text", "task", "reflection", "habit", "stay")
# A stay's item: "- [ ] accommodation: Airbnb near Alfama" ("- [x] " once sorted).
STAY_ITEM = re.compile(r"^- \[([ xX])\] ([^:]*?)\s*(?::\s?(.*))?$")
# What a day's first stay lists, when no stay was written before it.
STAY_ITEMS = ("place", "accommodation")


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


def _folded(block: dict[str, Any]) -> list[Any]:
    folded = block.get("folded") or []
    if not isinstance(folded, list):
        raise DomainError("A text block's folded rows are a list")
    return folded


def _row(row: Any) -> int:
    try:
        return int(row)
    except (TypeError, ValueError) as exc:
        raise DomainError(f"Not a row: {row!r}") from exc


def normalize(db: Session, blocks: Any) -> list[dict[str, Any]]:
    """Blocks as the page stores them: known shapes only, prose as written
    (blank lines kept between other blocks, not at the page's top or
    bottom), reflections without blank edges, adjacent prose joined, each
    task once.

    A text block may carry `links`, {row: task id}, naming the rows that
    are tasks (the notepad's "- [ ] " rows), and `folded`, the task rows
    shown folded to their title; they follow the text as the page's blank
    top lines are trimmed, and only known tasks are kept."""
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
        # Prose keeps its blank lines (the notes' spacing), except at the
        # page's top and bottom. A reflection's or habit's words keep a blank
        # first line (written under its first row, not on it) but none after.
        lines = _clean_text(block.get("text", "")).split("\n")
        last = index == len(blocks) - 1
        lead = 0
        if kind == "text" and not out:
            while lead < len(lines) and not lines[lead].strip():
                lead += 1
        end = len(lines)
        if kind != "text" or last:
            while end > lead and not lines[end - 1].strip():
                end -= 1
        text = "\n".join(lines[lead:end])
        if kind == "habit":
            # By name as written (or its id, as a page keeps it).
            ref = block.get("habit")
            if isinstance(ref, int):
                habit = db.get(Habit, ref)
                if habit is None:
                    continue
                slug = habit.slug
            else:
                slug = habits_svc.clean_slug(ref)
            done = block.get("done", True) is not False
            out.append({"kind": "habit", "habit": slug, "done": done, "text": text})
            continue
        if not text.strip() and (kind in ("reflection", "stay") or not out or last):
            continue
        links: dict[int, int] = {}
        folded: set[int] = set()
        if kind == "text":
            for row, task_id in _links(block).items():
                at = _row(row) - lead
                if task_id in known and 0 <= at < end - lead:
                    links[at] = task_id
            for row in _folded(block):
                at = _row(row) - lead
                if 0 <= at < end - lead:
                    folded.add(at)
        if kind == "text" and out and out[-1]["kind"] == "text":
            shift = out[-1]["text"].count("\n") + 1
            out[-1]["text"] += "\n" + text
            merged = {int(r): t for r, t in out[-1].get("links", {}).items()}
            merged |= {r + shift: t for r, t in links.items()}
            if merged:
                out[-1]["links"] = {str(r): t for r, t in sorted(merged.items())}
            joined = set(out[-1].get("folded", [])) | {r + shift for r in folded}
            if joined:
                out[-1]["folded"] = sorted(joined)
        else:
            out.append({"kind": kind, "text": text})
            if links:
                out[-1]["links"] = {str(r): t for r, t in sorted(links.items())}
            if folded:
                out[-1]["folded"] = sorted(folded)
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
    blocks = normalize(db, blocks)
    # The day's habit checks are the page's; the page keeps each by id.
    ids = habits_svc.sync_day(db, day, [b for b in blocks if b["kind"] == "habit"])
    page.blocks = [
        {**b, "habit": ids[b["habit"]]} if b["kind"] == "habit" else b for b in blocks
    ]
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
        elif block["kind"] == "habit":
            habit = db.get(Habit, block["habit"])
            if habit is not None:
                out.append({**block, "slug": habit.slug})
        else:
            out.append(dict(block))
    return out


def stay_items(text: str) -> list[dict[str, Any]]:
    """A stay's items, in order: each a name (as written, trimmed), its value
    and whether it is sorted. Its other lines are its note."""
    items = []
    for line in text.split("\n"):
        item = STAY_ITEM.match(line.strip())
        if item and item[2].strip():
            items.append({
                "name": item[2].strip(), "value": (item[3] or "").strip(), "done": item[1] in "xX",
            })
    return items


def last_stay_items(db: Session, day: date) -> list[str]:
    """The items the stay written last before `day` lists (a new stay starts
    with them), or place and accommodation."""
    pages = db.scalars(
        select(NotebookPage)
        .where(NotebookPage.day < day)
        .order_by(NotebookPage.day.desc())
        .limit(60)
    )
    for page in pages:
        for block in reversed(page.blocks):
            if block["kind"] == "stay":
                names = [item["name"] for item in stay_items(block["text"])]
                if names:
                    return names
    return list(STAY_ITEMS)


def task_ids_on(db: Session, day: date) -> list[int]:
    """Tasks the day's page holds, in the order it reads: its rows that made
    tasks, and those written there or referenced by it."""
    ids: list[int] = []
    for block in blocks_of(db, day):
        if block["kind"] == "task":
            ids.append(block["id"])
        elif block["kind"] == "text":
            links = block.get("links") or {}
            ids += [links[row] for row in sorted(links, key=int)]
    return list(dict.fromkeys(ids))


def still_open(db: Session, day: date) -> tuple[date | None, list[Task]]:
    """What a day's page offers to bring over: the last page before it that
    holds tasks, and those of them still open and to be worked by `day` (no
    do-date, or one not after it), in the order that page has them."""
    earlier_days = db.scalars(
        select(NotebookPage.day)
        .where(NotebookPage.day < day)
        .order_by(NotebookPage.day.desc())
        .limit(60)
    )
    for earlier in earlier_days:
        ids = task_ids_on(db, earlier)
        tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_(ids)))}
        if not tasks:
            continue
        return earlier, [
            tasks[i] for i in ids
            if i in tasks
            and tasks[i].status in tasks_svc.OPEN_STATUSES
            and (tasks[i].planned_for is None or tasks[i].planned_for <= day)
        ]
    return None, []


def version_of(db: Session, day: date) -> int:
    page = get_page(db, day)
    return page.version if page else 0
