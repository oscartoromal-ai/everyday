"""Sub-tasks written inline in a task's free-form description.

A task's notes are its description. Any line that reads like a Markdown list
item is a sub-task, and every other line is context that stays where it was
written, between the sub-tasks it explains:

    - fetch the feed          open sub-task
    - [ ] fetch the feed      open sub-task (explicit box)
    - [x] parse VEVENTs       done sub-task
    * dedupe instances        "*" works too; indent to nest

The text stays the single source of truth: ticking a sub-task rewrites its
own line and nothing else, so Oscar's wording, order and context survive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_ITEM = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*])[ \t]+(?:\[(?P<box>[ xX])\][ \t]+)?(?P<text>\S.*)$"
)


@dataclass(frozen=True)
class Line:
    kind: Literal["text", "item", "blank"]
    # A text line keeps its raw form, indentation included; an item holds its
    # words without marker or box.
    text: str
    # Items only: position among the description's items, done-ness, nesting.
    index: int | None = None
    checked: bool = False
    depth: int = 0


def normalize(notes: str) -> str:
    """One line ending, no trailing spaces, no blank lines at either edge."""
    lines = [line.rstrip() for line in notes.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def parse(notes: str) -> list[Line]:
    out: list[Line] = []
    index = 0
    for raw in notes.split("\n"):
        match = _ITEM.match(raw)
        if match:
            indent = match["indent"].expandtabs(4)
            out.append(
                Line(
                    kind="item",
                    text=match["text"],
                    index=index,
                    checked=(match["box"] or " ").lower() == "x",
                    depth=len(indent) // 2,
                )
            )
            index += 1
        elif raw.strip():
            out.append(Line(kind="text", text=raw))
        else:
            out.append(Line(kind="blank", text=""))
    return out


def progress(notes: str) -> tuple[int, int]:
    """(done, total) sub-tasks."""
    items = [line for line in parse(notes) if line.kind == "item"]
    return sum(1 for i in items if i.checked), len(items)


def _set_checked(match: re.Match[str], checked: bool) -> str:
    box = "[x] " if checked else ""
    return f"{match['indent']}{match['marker']} {box}{match['text']}"


def toggle(notes: str, index: int, expected_text: str) -> str | None:
    """Flip the index-th sub-task, or None when it is not `expected_text`.

    The caller saw the description at some earlier moment; if it has changed
    since (edited here, or by Claude), flipping by position alone could tick
    the wrong line, so a mismatch refuses instead.
    """
    raw_lines = notes.split("\n")
    seen = 0
    for n, raw in enumerate(raw_lines):
        match = _ITEM.match(raw)
        if not match:
            continue
        if seen == index:
            if match["text"] != expected_text:
                return None
            checked = (match["box"] or " ").lower() == "x"
            raw_lines[n] = _set_checked(match, not checked)
            return "\n".join(raw_lines)
        seen += 1
    return None


def reset(notes: str) -> str:
    """Every sub-task open again, as for a fresh occurrence of a repeating task."""
    out = []
    for raw in notes.split("\n"):
        match = _ITEM.match(raw)
        checked = match is not None and (match["box"] or "").lower() == "x"
        out.append(_set_checked(match, False) if checked else raw)
    return "\n".join(out)
