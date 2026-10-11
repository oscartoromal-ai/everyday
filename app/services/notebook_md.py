"""A day's notes as their file, notebook/<year>/<day>.md (SPEC.md, Files
first): the notes as Today's notepad has them, so the file reads as Oscar
wrote it:

    Slow morning. Called Ana.
    - [ ] Buy the tickets <!-- task:42 -->
    →its description, a tab in
    /reflection Calmer than yesterday.
    /habit morning-skin-care
    /habit [ ] running too tired
    /stay
    →- [ ] place: Lisbon
    →- [x] accommodation: Airbnb near Alfama

A task's row ends in "<!-- task:<id> -->" ("<!-- task:<id> folded -->"
when it shows folded to its title): the task it made. A reflection's,
habit's or stay's other rows are tabbed in (→ above is a tab), as a
task's description is.

blocks_text writes a page's blocks so; parse reads them back as the
notepad's save would (notepad.js, serialize).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Habit, Task, TaskStatus

TAB = "\t"
TASK_ROW = re.compile(r"^- \[([ xX])\] ")
MARK = re.compile(r"\s*<!-- task:(\d+)( folded)? -->\s*$")
REFLECTION = re.compile(r"^/reflection(?: |$)")
HABIT = re.compile(r"^/habit (?:\[([ xX])\] )?")
STAY = re.compile(r"^/stay(?: |$)")
HABIT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


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
        if kind == "habit":
            habit = db.get(Habit, block["habit"]) if isinstance(block["habit"], int) else None
            slug = habit.slug if habit else str(block["habit"])
            first, *rest = block["text"].split("\n")
            box = "" if block.get("done", True) else "[ ] "
            lines.append(f"/habit {box}{slug} {first}".rstrip(" "))
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
    them: the text between reflections, habits and stays (each task row's
    task by its row, `links`, and the rows shown folded, `folded`), each
    reflection's and stay's words, and each habit (by name, done or not, its
    note). A habit row whose name is not one stays text."""
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
            else "habit" if HABIT.match(line)
            else "stay" if STAY.match(line)
            else None
        )
        habit = None
        if kind == "habit":
            lead = HABIT.match(line)
            assert lead is not None
            rest = line[lead.end():]
            name = re.match(r"\S*", rest)[0]  # type: ignore[index]
            habit = {
                "slug": name.lower(),
                "done": lead[1] is None or lead[1] in "xX",
                "note": re.sub(r"^ ", "", rest[len(name):]),
            }
            if not HABIT_NAME.match(habit["slug"]):
                kind = None
        if kind is not None:
            end_text()
            last = n
            while last + 1 < len(lines) and lines[last + 1].startswith(TAB):
                last += 1
            words = [habit["note"] if habit else line[_lead(line, kind):]]
            words += [lines[k][1:] for k in range(n + 1, last + 1)]
            if habit:
                out.append({
                    "kind": "habit", "habit": habit["slug"], "done": habit["done"],
                    "text": "\n".join(words),
                })
            else:
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
