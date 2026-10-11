"""Sub-tasks written inline in a task's free-form description.

A task's notes are its description, Markdown as GitHub reads it. A list item
with a box is a sub-task; a list item without one is a bullet, as in any
Markdown; every other line is context that stays where it was written,
between the sub-tasks it explains:

    - [ ] fetch the feed      open sub-task
    - [x] parse VEVENTs       done sub-task
    * [ ] dedupe instances    "*" and "+" work too; indent to nest
    - ICS, not CalDAV         a bullet: not a sub-task (Oscar's call on 2026-10-11)

Lines in a fenced code block ("```" to "```") are code, whatever they read.

The text stays the single source of truth: ticking a sub-task rewrites its
own line and nothing else, so Oscar's wording, order and context survive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_LIST = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*+])[ \t]+(?:\[(?P<box>[ xX])\][ \t]+)?(?P<text>\S.*)$"
)
_FENCE = re.compile(r"^[ \t]{0,3}(?P<marks>`{3,}|~{3,})")


@dataclass(frozen=True)
class Line:
    kind: Literal["text", "item", "bullet", "blank"]
    # A text line keeps its raw form, indentation included; an item or a
    # bullet holds its words without marker or box.
    text: str
    # Items only: position among the description's items, done-ness.
    index: int | None = None
    checked: bool = False
    # Items and bullets: nesting.
    depth: int = 0


def normalize(notes: str) -> str:
    """One line ending, no trailing spaces, no blank lines at either edge."""
    lines = [line.rstrip() for line in notes.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _matches(notes: str) -> list[re.Match[str] | None]:
    """Each line's list match, or None: not a list item, or in fenced code."""
    out: list[re.Match[str] | None] = []
    fence: str | None = None  # the open fence's marks, while in a fenced block
    for raw in notes.split("\n"):
        if fence is not None:
            if re.fullmatch(rf"[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", raw):
                fence = None
            out.append(None)
        elif opens := _FENCE.match(raw):
            fence = opens["marks"]
            out.append(None)
        else:
            out.append(_LIST.match(raw))
    return out


def parse(notes: str) -> list[Line]:
    out: list[Line] = []
    index = 0
    for raw, match in zip(notes.split("\n"), _matches(notes), strict=True):
        if match:
            depth = len(match["indent"].expandtabs(4)) // 2
            if match["box"] is None:
                out.append(Line(kind="bullet", text=match["text"], depth=depth))
                continue
            out.append(
                Line(
                    kind="item",
                    text=match["text"],
                    index=index,
                    checked=match["box"].lower() == "x",
                    depth=depth,
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
    box = "[x]" if checked else "[ ]"
    return f"{match['indent']}{match['marker']} {box} {match['text']}"


def _items(notes: str) -> list[tuple[int, re.Match[str]]]:
    """(line number, match) of each sub-task, in order."""
    return [
        (n, match)
        for n, match in enumerate(_matches(notes))
        if match is not None and match["box"] is not None
    ]


def toggle(notes: str, index: int, expected_text: str) -> str | None:
    """Flip the index-th sub-task, or None when it is not `expected_text`.

    The caller saw the description at some earlier moment; if it has changed
    since (edited here, or by Claude), flipping by position alone could tick
    the wrong line, so a mismatch refuses instead.
    """
    items = _items(notes)
    if not 0 <= index < len(items):
        return None
    n, match = items[index]
    if match["text"] != expected_text:
        return None
    raw_lines = notes.split("\n")
    raw_lines[n] = _set_checked(match, match["box"].lower() != "x")
    return "\n".join(raw_lines)


def reset(notes: str) -> str:
    """Every sub-task open again, as for a fresh occurrence of a repeating task."""
    raw_lines = notes.split("\n")
    for n, match in _items(notes):
        if match["box"].lower() == "x":
            raw_lines[n] = _set_checked(match, False)
    return "\n".join(raw_lines)
