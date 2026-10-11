"""A task as its file, task.md, in its folder (SPEC.md, Files first):

    ---
    # (what the front matter is)
    id: 12
    title: Fix the feed
    status: in_progress
    ...
    ---

    The description, Markdown, its "- [ ] " lines sub-tasks.

    ## Acceptance

    What done means.

    ## Outcome

    What came of it.

The front matter is the database's, written by the app and written back
over an edit made in the file; the description, acceptance criteria and
outcome are the file's. Both sections are always written, last, so the last
"## Acceptance" and "## Outcome" lines (outside fenced code) are theirs, a
description's own headings of those words before them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app import checklist
from app.models import Task
from app.services import everyday

NOTE = (
    "Personal Calendar keeps these fields: an edit here is put back. Change them in the app,\n"
    "over its API (README.md at the everyday files' top) or through Claude's tools.\n"
    "The words below (description, acceptance, outcome) are this file's: write them here."
)
ACCEPTANCE = "## Acceptance"
OUTCOME = "## Outcome"
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def fields(task: Task) -> dict[str, Any]:
    """The task's fields as its front matter has them."""
    data: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "owner": task.owner.value,
        "project": task.project.name if task.project else None,
        "workstream": task.workstream.name if task.workstream else None,
        "priority": task.priority.value if task.priority else None,
        "planned_for": task.planned_for,
        "due": task.due,
        "starts_on": task.starts_on,
        "estimate_minutes": task.estimate_minutes,
    }
    if task.written_on:
        data["written_on"] = task.written_on
    if task.recurrence_template_id:
        data["occurrence_date"] = task.occurrence_date
    if task.repos:
        data["repos"] = [r.location for r in task.repos]
    if task.pull_requests:
        data["pull_requests"] = [
            f"{pr.repo}#{pr.number} ({pr.state.value})" for pr in task.pull_requests
        ]
    data["created_at"] = task.created_at.replace(microsecond=0) if task.created_at else None
    return data


def render(task: Task) -> str:
    """The task's file as the database has it."""
    out = everyday.front_matter(NOTE, fields(task)) + "\n"
    if task.notes.strip():
        out += task.notes.strip("\n") + "\n\n"
    out += ACCEPTANCE + "\n\n"
    if task.acceptance.strip():
        out += task.acceptance.strip("\n") + "\n\n"
    out += OUTCOME + "\n"
    if task.outcome.strip():
        out += "\n" + task.outcome.strip("\n") + "\n"
    return out


@dataclass
class Words:
    """What a task's file says in words, and what its front matter says."""

    notes: str
    acceptance: str
    outcome: str
    front: dict[str, Any] | None


def _headings(lines: list[str]) -> tuple[int | None, int | None]:
    """The rows of the last "## Acceptance" and of the last "## Outcome" after
    it, outside fenced code."""
    acceptance = outcome = None
    fence: str | None = None
    for row, line in enumerate(lines):
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        if opens := _FENCE.match(line):
            fence = opens[1]
            continue
        if line.rstrip() == ACCEPTANCE:
            acceptance, outcome = row, None
        elif line.rstrip() == OUTCOME:
            outcome = row
    return acceptance, outcome


def parse(text: str) -> Words:
    """A task's file read: its words, each as the task keeps it, and its
    front matter. A file missing a section has none of its words."""
    front, body = everyday.split_front_matter(everyday.plain(text))
    lines = body.split("\n")
    acceptance_at, outcome_at = _headings(lines)
    end = len(lines)
    outcome = acceptance = ""
    if outcome_at is not None:
        outcome = "\n".join(lines[outcome_at + 1:])
        end = outcome_at
    if acceptance_at is not None:
        acceptance = "\n".join(lines[acceptance_at + 1:end])
        end = acceptance_at
    elif outcome_at is None:
        end = len(lines)
    return Words(
        notes=checklist.normalize("\n".join(lines[:end])),
        acceptance=acceptance.strip("\n").strip(),
        outcome=outcome.strip("\n").strip(),
        front=front,
    )


def new_task_fields(front: dict[str, Any] | None) -> dict[str, Any]:
    """What a task made from a file takes from its front matter: its title,
    and the fields create_task takes, each as written when it reads as one
    (the rest left out)."""
    from app.models import TaskOwner, TaskPriority, TaskStatus

    front = front or {}
    out: dict[str, Any] = {}
    if isinstance(front.get("title"), str) and front["title"].strip():
        out["title"] = front["title"].strip()
    for key, kind in (("status", TaskStatus), ("owner", TaskOwner), ("priority", TaskPriority)):
        value = front.get(key)
        if isinstance(value, str) and value in kind.__members__:
            out[key] = kind(value)
    for key in ("planned_for", "due", "starts_on"):
        day = everyday.as_date(front.get(key))
        if day is not None:
            out[key] = day
    minutes = front.get("estimate_minutes")
    if isinstance(minutes, int) and 0 < minutes <= 24 * 60:
        out["estimate_minutes"] = minutes
    # A task made by a file starts open: done is Oscar's, or its pull requests'.
    if out.get("status") in (TaskStatus.done, TaskStatus.cancelled):
        del out["status"]
    return out
