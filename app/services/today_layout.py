"""Today's layout: its panes (the plan, the habits, the stay, the work, the
notes, the timeline) in three columns, at the left, in the middle and at
the right, in the order Oscar dragged them, and the panes he hid. Kept as
the "today" setting, so it holds on every device and on every day's page. A
hidden pane keeps its place, and comes back to it; a pane the code adds
later joins its own column's end."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Setting
from app.services import DomainError

SETTING = "today"


@dataclass(frozen=True)
class Pane:
    key: str
    label: str
    # The column it starts in: 0 at the left, 1 in the middle, 2 at the right.
    column: int


PANES: tuple[Pane, ...] = (
    Pane("plan", "Plan", 0),
    Pane("habits", "Habits", 0),
    Pane("stay", "Stay", 0),
    Pane("work", "Work", 0),
    Pane("notes", "Notes", 1),
    Pane("timeline", "Timeline", 2),
)
_PANES = {p.key: p for p in PANES}
COLUMNS = ("left", "center", "right")


@dataclass(frozen=True)
class PlacedPane:
    pane: Pane
    hidden: bool


@dataclass(frozen=True)
class Column:
    key: str
    panes: tuple[PlacedPane, ...]

    @property
    def empty(self) -> bool:
        """No pane showing in it: the column goes, its room the others'."""
        return all(p.hidden for p in self.panes)


def _placed(columns: list[list[str]]) -> list[list[str]]:
    """The columns given, each pane once and only known ones, the panes not
    given at their own column's end."""
    seen: set[str] = set()
    placed: list[list[str]] = []
    for i in range(len(COLUMNS)):
        keys = columns[i] if i < len(columns) else []
        own = [k for k in keys if k in _PANES and k not in seen]
        seen.update(own)
        placed.append(own)
    for pane in PANES:
        if pane.key not in seen:
            placed[pane.column].append(pane.key)
    return placed


def default_columns() -> list[list[str]]:
    """The panes' columns as the code lists them, as Reset sets them back."""
    return _placed([])


def layout(db: Session | None) -> list[Column]:
    """The three columns, each with its panes in order, hidden ones in their
    places; as the code lists them with no session to read the setting from."""
    setting = None if db is None else db.get(Setting, SETTING)
    saved = setting.value if setting and isinstance(setting.value, dict) else {}
    columns = saved.get("columns")
    hidden = set(saved.get("hidden", []))
    placed = _placed(columns if isinstance(columns, list) else [])
    return [
        Column(key, tuple(PlacedPane(_PANES[k], k in hidden) for k in keys))
        for key, keys in zip(COLUMNS, placed, strict=True)
    ]


def save_layout(db: Session, *, columns: list[list[str]], hidden: list[str]) -> None:
    """The panes in each of the three columns, and those hidden."""
    if len(columns) != len(COLUMNS):
        raise DomainError(f"Today has {len(COLUMNS)} columns, not {len(columns)}")
    for key in [k for keys in columns for k in keys] + hidden:
        if key not in _PANES:
            raise DomainError(f"No pane {key}")
    value = {"columns": _placed(columns), "hidden": sorted(set(hidden))}
    setting = db.get(Setting, SETTING)
    if setting is None:
        db.add(Setting(key=SETTING, value=value))
    else:
        setting.value = value
    db.flush()
