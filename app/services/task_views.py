"""The views a project's Tasks tab is drawn in, and the one Oscar chose
from its gear: kept as the "tasks_view" setting, so every project's tab
opens in it, on every device.

What is folded, shown or picked in a view is kept on the device, in a
cookie of the project's Tasks tab (tasks-views.js writes it), so the page
is drawn as it was left from its first paint."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import unquote

from sqlalchemy.orm import Session

from app.models import Setting
from app.services import DomainError

SETTING = "tasks_view"
# The cookie each project's Tasks tab keeps its views' state in, its path
# the tab's own (/projects/<id>/tasks), so only that page is sent it.
STATE_COOKIE = "tasks-state"


@dataclass(frozen=True)
class View:
    key: str
    label: str
    # What it is, a line under its name in the gear's menu.
    about: str
    # It has a script of its own (static/tasks-<key>.js).
    script: bool = False


VIEWS: tuple[View, ...] = (
    View("list", "List", "A card for each workstream, each task with its details under it"),
    View("table", "Table", "A row for each task, its details in columns"),
    View(
        "pane",
        "List and details",
        "A line for each task, the one picked in a pane beside",
        script=True,
    ),
    View("board", "Board", "A column for each workstream, a card for each task", script=True),
    View("schedule", "By do-date", "Overdue, today, tomorrow, the week and later"),
)
_VIEWS = {v.key: v for v in VIEWS}
DEFAULT = "list"
# The views with a row of their own (partials/project_tasks/<key>_row.html),
# which a task's row drawn again in them comes back as; the list's is the
# task row every other list has.
ROW_VIEWS = frozenset(v.key for v in VIEWS if v.key != DEFAULT)


def get(key: str) -> View:
    try:
        return _VIEWS[key]
    except KeyError:
        raise DomainError(f"No such view: {key}") from None


def current(db: Session) -> View:
    """The view chosen, or the list while none is (or one since gone is)."""
    setting = db.get(Setting, SETTING)
    return _VIEWS.get(setting.value if setting else DEFAULT, _VIEWS[DEFAULT])


def choose(db: Session, key: str) -> View:
    view = get(key)
    setting = db.get(Setting, SETTING)
    if setting is None:
        db.add(Setting(key=SETTING, value=view.key))
    else:
        setting.value = view.key
    db.flush()
    return view


@dataclass(frozen=True)
class State:
    """How a view was left: the parts folded (their data-fold-key), the
    tasks whose sub-tasks are shown, Show completed ticked or not, and the
    task picked (List and details)."""

    folds: frozenset[str] = field(default_factory=frozenset)
    subtasks: frozenset[int] = field(default_factory=frozenset)
    done: bool = False
    picked: int | None = None

    def folded(self, key: str) -> bool:
        return key in self.folds

    def shows(self, task_id: int) -> bool:
        return task_id in self.subtasks


def state(cookie: str | None, view: str) -> State:
    """A view's state as the tab's cookie has it: a JSON object by view
    ({"table": {"folds": [...], "subtasks": [...], "done": true}}), written
    URI-encoded. Anything it cannot read is no state at all."""
    try:
        mine = json.loads(unquote(cookie or "")).get(view) or {}
        picked = mine.get("picked")
        return State(
            folds=frozenset(str(k) for k in mine.get("folds") or ()),
            subtasks=frozenset(int(i) for i in mine.get("subtasks") or ()),
            done=mine.get("done") is True,
            picked=int(picked) if picked is not None else None,
        )
    except (ValueError, TypeError, AttributeError):
        return State()
