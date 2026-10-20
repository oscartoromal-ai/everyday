"""A habit as its file, habits/<name>.md in the everyday files (SPEC.md,
Files first): front matter the database's (its id, name, days and since
when), written by the app and written back over an edit made in the file;
then the habit's words, the file's: what it is, and its log, a comment a
day, the newest first:

    What it is, why, how.

    ## Log

    - 2026-10-20: Knee sore, walked instead.
      Ran the last kilometre.
    - 2026-10-14: 5k, felt easy.

An entry's other lines are indented under it. Whether a day was done is
the database's (the habit's checks), never the file's: a comment on a day
not ticked says why it was skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models import Habit
from app.services import everyday

LOG = "## Log"
# An entry's first line: "- 2026-10-20: words" (the colon optional).
ENTRY = re.compile(r"^[-*] (\d{4}-\d{2}-\d{2})\b:?[ \t]*(.*)$")
INDENT = "  "

NOTE = (
    "Personal Calendar keeps these fields: an edit here is put back. Change them in the app,\n"
    "over its API (README.md at the everyday files' top) or through Claude's tools; a day is\n"
    "ticked on Today's habits pane or Calendar's sheet.\n"
    "The words below, what the habit is and its log (a comment a day), are this file's."
)

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def days_label(days: str) -> str:
    """A habit's days in words, as its days' icon says them."""
    if not days:
        return "Any day"
    if days == "0123456":
        return "Every day"
    if days == "01234":
        return "Weekdays"
    if days == "56":
        return "Weekends"
    return ", ".join(WEEKDAYS[int(d)] for d in days)


def days_of(label: Any) -> str:
    """A habit's days as its front matter says them (days_label's words, or
    weekdays' names, "Mon, Thu"), for a habit made from its file; any day
    when they say nothing it knows."""
    if not isinstance(label, str):
        return ""
    words = label.strip().lower()
    named = {"every day": "0123456", "weekdays": "01234", "weekends": "56"}
    if words in named:
        return named[words]
    days = set()
    for word in re.split(r"[\s,]+", words):
        known = [i for i, name in enumerate(WEEKDAYS) if word[:3] == name.lower()]
        if not known:
            return ""
        days.add(str(known[0]))
    return "".join(sorted(days))


def fields(habit: Habit) -> dict[str, Any]:
    return {
        "id": habit.id,
        "name": habit.slug,
        "days": days_label(habit.days),
        "since": habit.created_at.date().isoformat(),
    }


def body(notes: str, log: dict[date, str]) -> str:
    """The file's words: what the habit is, then its log, the newest day first."""
    out = notes.strip("\n") + "\n\n" if notes.strip() else ""
    out += LOG + "\n"
    entries = []
    for day in sorted(log, reverse=True):
        first, *rest = log[day].strip().split("\n")
        lines = [f"- {day.isoformat()}: {first}".rstrip()]
        lines += [f"{INDENT}{line}".rstrip() for line in rest]
        entries.append("\n".join(lines))
    if entries:
        out += "\n" + "\n".join(entries) + "\n"
    return out


def render(habit: Habit, log: dict[date, str]) -> str:
    return everyday.front_matter(NOTE, fields(habit)) + "\n" + body(habit.notes, log)


@dataclass
class Words:
    """What a habit's file says: what it is, and its comments by day."""

    notes: str = ""
    log: dict[date, str] = field(default_factory=dict)


def parse(text: str) -> Words:
    """A habit's file read: its words above "## Log" what it is, and under
    it each day's comment (an entry's indented lines with it; a day written
    twice, both). A line under the log before its first entry, or a day that
    is not one, stays with what the habit is, so nothing written is lost."""
    _, words = everyday.split_front_matter(everyday.plain(text))
    lines = words.split("\n")
    head = next((i for i, line in enumerate(lines) if line.strip() == LOG), len(lines))
    notes = lines[:head]
    log: dict[date, list[str]] = {}
    current: list[str] | None = None
    for line in lines[head + 1 :]:
        entry = ENTRY.match(line)
        day = _day(entry[1]) if entry else None
        if entry and day is not None:
            current = log.setdefault(day, [])
            current.append(entry[2].rstrip())
        elif current is not None and (not line.strip() or line[:1] in " \t"):
            current.append(line.strip())
        elif line.strip():
            current = None
            notes.append(line)
    return Words(
        notes="\n".join(notes).strip("\n"),
        log={day: text for day, parts in log.items() if (text := "\n".join(parts).strip())},
    )


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
