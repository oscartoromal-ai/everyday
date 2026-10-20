"""A day's notes as their file, notebook/<year>/<day>.md (SPEC.md, Files
first): the notes as Today's notepad has them, so the file reads as Oscar
wrote it:

    Slow morning. Called Ana.
    - [ ] Buy the tickets <!-- task:42 -->
    →its description, a tab in
    /reflection Calmer than yesterday.
    /stay
    →- [ ] place: Lisbon
    →- [x] accommodation: Airbnb near Alfama

A task's row ends in "<!-- task:<id> -->" ("<!-- task:<id> folded -->"
when it shows folded to its title): the task it made. A reflection's or
stay's other rows are tabbed in (→ above is a tab), as a task's
description is. Habits are not in the notes: each has a file of its own
(app.services.habit_md).

blocks_text writes a page's blocks so; parse reads them back as the
notepad's save would (notepad.js, serialize).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Task, TaskStatus

TAB = "\t"
TASK_ROW = re.compile(r"^- \[([ xX])\] ")
MARK = re.compile(r"\s*<!-- task:(\d+)( folded)? -->\s*$")
REFLECTION = re.compile(r"^/reflection(?: |$)")
STAY = re.compile(r"^/stay(?: |$)")


def _mark(task_id: int, folded: bool) -> str:
    return f" <!-- task:{task_id}{' folded' if folded else ''} -->"


def blocks_text(db: Session, blocks: list[dict[str, Any]]) -> str:
    """A page's blocks (as the page keeps them) as its file's words."""
    from app.services.history import last_known

    lines: list[str] = []
    refs = [b["id"] for b in blocks if b["kind"] == "task"]
    tasks = {t.id: t for t in db.query(Task).filter(Task.id.in_(refs))} if refs else {}
    gone = last_known(db, [i for i in refs if i not in tasks]) if refs else {}
    for block in blocks:
        kind = block["kind"]
        if kind == "task":
            # A task referenced, from the notebook's time: its row, as the notepad shows it.
            task = tasks.get(block["id"])
            title = task.title if task else gone.get(block["id"], {}).get("title", "")
            if title:
                box = "x" if task and task.status == TaskStatus.done else " "
                lines.append(f"- [{box}] {title}" + (_mark(task.id, False) if task else ""))
            continue
        if kind in ("reflection", "stay"):
            first, *rest = block["text"].split("\n")
            lines.append(f"/{kind} {first}".rstrip(" "))
            lines.extend(f"{TAB}{line}" for line in rest)
            continue
        rows = block["text"].split("\n")
        links = {int(r): t for r, t in (block.get("links") or {}).items()}
        folded = {int(r) for r in block.get("folded") or []}
        for row, line in enumerate(rows):
            if row in links and TASK_ROW.match(line):
                line = MARK.sub("", line) + _mark(links[row], row in folded)
            lines.append(line)
    text = "\n".join(lines)
    return text + "\n" if text else ""


def _lead(line: str, kind: str) -> int:
    pattern = REFLECTION if kind == "reflection" else STAY
    found = pattern.match(line)
    return found.end() if found else 0


def parse(text: str) -> list[dict[str, Any]]:
    """A day's file read as the page's blocks, as the notepad would save
    them: the text between reflections and stays (each task row's task by
    its row, `links`, and the rows shown folded, `folded`), and each
    reflection's and stay's words."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out: list[dict[str, Any]] = []
    rows: list[str] | None = None
    links: dict[str, int] = {}
    folded: list[int] = []

    def end_text() -> None:
        nonlocal rows, links, folded
        if rows is None:
            return
        block: dict[str, Any] = {"kind": "text", "text": "\n".join(rows)}
        if links:
            block["links"] = links
        if folded:
            block["folded"] = folded
        out.append(block)
        rows, links, folded = None, {}, []

    n = 0
    while n < len(lines):
        line = lines[n]
        kind = (
            "reflection" if REFLECTION.match(line)
            else "stay" if STAY.match(line)
            else None
        )
        if kind is not None:
            end_text()
            last = n
            while last + 1 < len(lines) and lines[last + 1].startswith(TAB):
                last += 1
            words = [line[_lead(line, kind):]]
            words += [lines[k][1:] for k in range(n + 1, last + 1)]
            out.append({"kind": kind, "text": "\n".join(words)})
            n = last + 1
            continue
        if rows is None:
            rows = []
        mark = MARK.search(line) if TASK_ROW.match(line) else None
        if mark:
            line = line[: mark.start()]
            links[str(len(rows))] = int(mark[1])
            if mark[2]:
                folded.append(len(rows))
        rows.append(line)
        n += 1
    end_text()
    return out
