"""The app's keys: every action a key can do, the keys it does it on, and
the ones Oscar chose instead.

Each action has an id ("task.done"), a name, where it works (its scope: a
page, the Projects list, a sheet, or anywhere) and its default keys. The
keys he chose are kept in keys.toml in the app's home, over the defaults
action by action: written by Keyboard (/keys, from Settings), or by hand in
any text editor, and read again as it changes, with no restart:

    [keys]
    "app.search" = "Ctrl+P"          # one key
    "task.new" = ["N", "Shift+N"]    # several
    "app.theme" = []                 # none

A key is written as its modifiers and then the key, joined by "+": Ctrl
(Cmd on a Mac), Alt, Shift; a letter or digit, a character ("?", "\\",
"-"), or a named key (ArrowLeft, Enter, Escape, Space, Tab, Delete,
Backspace, Home, End, PageUp, PageDown, F1 to F12). Shift is part of a
character typed with it ("?" is Shift+/ on most keyboards), so it is
written for letters, digits and named keys alone.

Some keys stay as they are, written down for the keys dialog (?) but not
rebound: moving in a sheet, writing in a field, a list's Home and End.
Keyboard lists every action and its keys, and so does GET /ui/keys, and
`uv run python -m app.services.keys` prints them.
"""

from __future__ import annotations

import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit
from markupsafe import Markup, escape
from tomlkit.exceptions import TOMLKitError

from app import config
from app.services import DomainError

FILE_NAME = "keys.toml"

# ---- writing a key ----

MODIFIERS = ("Ctrl", "Alt", "Shift")
_MODIFIER_NAMES = {
    "ctrl": "Ctrl", "control": "Ctrl", "ctl": "Ctrl", "cmd": "Ctrl", "command": "Ctrl",
    "meta": "Ctrl", "mod": "Ctrl", "super": "Ctrl", "win": "Ctrl",
    "alt": "Alt", "option": "Alt", "opt": "Alt",
    "shift": "Shift",
}
NAMED_KEYS = (
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape", "Space", "Tab",
    "Backspace", "Delete", "Insert", "Home", "End", "PageUp", "PageDown",
    *(f"F{n}" for n in range(1, 13)),
)
_KEY_NAMES = {k.lower(): k for k in NAMED_KEYS} | {
    "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
    "↑": "ArrowUp", "↓": "ArrowDown", "←": "ArrowLeft", "→": "ArrowRight",
    "return": "Enter", "esc": "Escape", "del": "Delete", "ins": "Insert",
    "pgup": "PageUp", "pgdn": "PageDown", "pagedn": "PageDown",
    "plus": "+", "minus": "-", "spacebar": "Space", " ": "Space",
}
# How a key is shown: arrows as arrows, the long names short.
_SHOWN = {
    "ArrowUp": "↑", "ArrowDown": "↓", "ArrowLeft": "←", "ArrowRight": "→",
    "Escape": "Esc", "PageUp": "PgUp", "PageDown": "PgDn",
}


def parse(combo: str) -> str:
    """A key as written, in its one spelling ("ctrl+shift+k" is
    "Ctrl+Shift+K"); a DomainError says what is wrong with one that is not
    a key."""
    text = combo.strip()
    if not text:
        raise DomainError("A key can't be empty")
    # "+" splits, except a "+" that is the key itself ("+", "Ctrl++").
    parts = re.split(r"\+(?!$)", text) if text != "+" else ["+"]
    *mods, key = (p.strip() for p in parts)
    held = set()
    for mod in mods:
        name = _MODIFIER_NAMES.get(mod.lower())
        if name is None:
            raise DomainError(f"{combo!r}: {mod!r} is not Ctrl, Alt or Shift")
        held.add(name)
    if key.lower() in _MODIFIER_NAMES:
        raise DomainError(f"{combo!r} is only modifiers: add the key they go with")
    if key.lower() in _KEY_NAMES:
        key = _KEY_NAMES[key.lower()]
    elif len(key) == 1 and key.isprintable():
        key = key.upper()
    else:
        raise DomainError(f"{combo!r}: {key!r} is not a key")
    # A character's Shift is in the character itself ("?", "!").
    if len(key) == 1 and not key.isalnum():
        held.discard("Shift")
    return "+".join([*(m for m in MODIFIERS if m in held), key])


def shown(combo: str) -> list[str]:
    """A key's parts as they are shown, each its own key cap."""
    return [_SHOWN.get(part, part) for part in re.split(r"\+(?!$)", combo)]


def text(combo: str) -> str:
    """A key in words, as a title or a toast says it: "Ctrl+K", "Alt+←"."""
    return "+".join(shown(combo))


# ---- the actions ----


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    keys: tuple[str, ...] = ()
    # What the key does, for an action done by clicking or focusing the
    # page's element (keys.js, with no script of its own), or going to a
    # page; with none of these, a page's script does it.
    click: str = ""
    focus: str = ""
    go: str = ""
    # Shown in the command menu (Ctrl+K), where the page has what it acts on.
    menu: bool = False
    # More words the command menu finds it by.
    words: str = ""
    # The module it belongs to, for one a machine can be installed without.
    module: str = ""
    # Done before the page's own keys (keys.js hears it first): a key that
    # works wherever the focus is, in a field or an editor too.
    first: bool = False


@dataclass(frozen=True)
class Fixed:
    """A key that stays as it is, written for the keys dialog: [Key] is a
    key cap, "or" goes between the keys that do the same."""

    keys: str
    label: str


@dataclass(frozen=True)
class Scope:
    id: str
    title: str
    entries: tuple[Action | Fixed, ...]
    # The column of the keys dialog it is in.
    column: int = 1
    module: str = ""
    # Said under its title on Keyboard: where its keys work.
    where: str = ""


def _go(module: str, label: str, href: str, words: str = "", section: str = "") -> Action:
    return Action(
        f"go.{module}", f"Go to {label}", go=href, words=f"page open {words}".strip(),
        module=section,
    )


SCOPES: tuple[Scope, ...] = (
    Scope("anywhere", "Anywhere", (
        Action("app.search", "Search tasks, projects, events and notes; go to a page or a day; "
               "or do", ("Ctrl+K",)),
        Action("app.keys", "These keys", ("?",), menu=True, words="keyboard shortcuts help"),
        Action("task.new", "New task (the sidebar's New task too, from any page)", ("N", "Shift+N"),
               menu=True, words="add write capture todo"),
        Action("event.new", "New event", ("E",), click="[data-new-event]", go="/calendar?new=1",
               menu=True, words="add calendar meeting"),
        Action("app.back", "Back to the page before, as you left it", ("Alt+ArrowLeft",),
               menu=True, words="previous history return"),
        Action("app.forward", "Forward again, to the page you came back from", ("Alt+ArrowRight",),
               menu=True, words="next history"),
        Action("day.prev", "The day before (or the days, the month, before) on a page of days",
               ("ArrowLeft",), click='[data-day-step="prev"]', words="previous earlier yesterday"),
        Action("day.next", "The day after (or the days, the month, after) on a page of days",
               ("ArrowRight",), click='[data-day-step="next"]', words="later tomorrow"),
        Action("day.today", "Back to today (this week on a Gantt, this month on Spending)", ("T",),
               click="a.day-today, a.week-today, [data-gantt-this-week]", menu=True,
               words="now current this week month"),
        Action("app.agent", "The agent window: open it, at its message, or collapse it", ("A",),
               menu=True, words="agent chat ask claude codex ai assistant expand collapse"),
        Action("page.add", "Write a new one: a project, document, weigh-in, bill, goal, account "
               "or category, in the page's own row for it", ("Shift+A",),
               focus=", ".join((
                   "form.new-project input[name=name]", "#doc-new", "#me-weigh-in",
                   "form.money-bill-form input:not([type=hidden])",
                   "form[hx-post='/ui/money/goals'] input:not([type=hidden])",
                   "form[hx-post='/ui/money/accounts'] input:not([type=hidden])",
                   "form.money-add[hx-post$='/categories'] input:not([type=hidden])",
               )), menu=True, words="add create new project document weigh bill goal account"),
        Action("page.find", "Find on the page (Repositories), else search", ("/",),
               focus=".repos-find input[type=search]", menu=False, words="filter search"),
        Action("page.sync", "Sync now: the work calendar, Garmin, GitHub or the models", ("R",),
               click=", ".join((
                   "[hx-post='/ui/work-sync']", "[hx-post='/ui/garmin/sync']",
                   "[hx-post='/ui/github/sync']", "[hx-post='/ui/models/check']",
               )), menu=True,
               words="refresh fetch reload check work calendar garmin github models"),
        Action("page.delete", "Delete this task or document, after asking", ("Ctrl+-",),
               click="form.task-sheet[data-sheet=page] .task-delete, .doc-title .task-delete",
               menu=True, words="remove bin trash"),
        Action("event.join", "Join the meeting (Today's next, or the open event's)", ("Alt+J",),
               click="a.glance-join, .event-join", menu=True, words="call video teams zoom meet"),
        Action("app.density", "Compact rows, or roomy again (the ruled sheets, Today's notes)",
               ("C",),
               click=".density-toggle", menu=True, words="compact roomy density rows"),
        Action("app.theme", "Switch to the other theme", ("Ctrl+Shift+L",), click=".theme-toggle",
               menu=True, words="dark light day night mode"),
        Action("app.sidebar", "Collapse the sidebar, or expand it", ("Ctrl+Shift+B",),
               click=".rail-collapse", menu=True, words="rail collapse expand hide menu"),
        Action("app.railProjects", "Fold the sidebar's projects away, or show them",
               click=".nav-fold", menu=True, words="rail projects fold"),
        Action("app.settings", "Settings", ("Ctrl+,",), click="[data-settings-open]", menu=True,
               words="preferences options modules version"),
        Action("app.keysPage", "Change the keys", go="/keys", menu=True,
               words="keyboard shortcuts hotkeys bindings rebind"),
        Action("app.changelog", "The changelog", go="/changelog", menu=False,
               words="version release what's new history"),
        Action("app.checkUpdates", "Check for updates", menu=True,
               words="upgrade download new version release latest"),
        Action("app.update", "Update the app, or restart it on its update", ("Ctrl+Shift+U",),
               click="button.update-button", menu=False,
               words="upgrade install build release restart"),
    )),
    Scope("go", "Pages", (
        *(Action(f"nav.slot{n}", f"The sidebar's page {n}, as it shows them", (f"Alt+{n}",))
          for n in range(1, 10)),
        _go("today", "Today", "/today"),
        _go("calendar", "Calendar", "/calendar"),
        _go("projects", "Projects", "/projects"),
        _go("plan", "Plan", "/plan", "tasks without a day undated schedule"),
        _go("nutrition", "Nutrition", "/nutrition", "food meals diet", "health"),
        _go("me", "Me", "/me", "body weight", "health"),
        _go("garmin", "Garmin", "/garmin", "watch sleep steps", "health"),
        _go("spending", "Spending", "/spending", "money budget", "finances"),
        _go("accounts", "Accounts", "/accounts", "money bank net worth", "finances"),
        _go("bills", "Bills", "/bills", "money", "finances"),
        _go("goals", "Goals", "/goals", "money savings", "finances"),
        _go("repositories", "Repositories", "/repositories", "github code repos", "code"),
        _go("models", "Models", "/models", "ai llm claude openai codex provider model"),
    ), where="Anywhere; the sidebar's are numbered from the top, hidden pages skipped"),
    Scope("agent", "Agent window", (
        Fixed("[Enter]", "Send the message ([Shift] [Enter]: a new line)"),
        Fixed("[Esc]", "Out of the message, back to the page"),
    ), where="In the agent window, docked at the right"),
    Scope("sidebar", "Sidebar", (
        Action("rail.up", "On a page or project: up a place", ("Alt+ArrowUp",)),
        Action("rail.down", "On a page or project: down a place", ("Alt+ArrowDown",)),
        Action("rail.sectionUp", "On a page: its whole section up a place", ("Alt+Shift+ArrowUp",)),
        Action("rail.sectionDown", "On a page: its whole section down a place",
               ("Alt+Shift+ArrowDown",)),
        Action("rail.hide", "On a page: hide it from the sidebar (Settings brings it back)",
               ("Delete",)),
        Fixed("Drag", "A page within its section, a project among the projects, or a section by "
              "its name (Projects by itself)"),
        Fixed("The eye", "Hides a page from the sidebar (its section goes once all its pages do); "
              "Settings brings it back"),
    ), where="With a page or project in the sidebar focused"),
    Scope("panes", "Panes", (
        Action("pane.left", "To the pane at the left", ("Ctrl+Alt+ArrowLeft",), first=True),
        Action("pane.right", "To the pane at the right", ("Ctrl+Alt+ArrowRight",), first=True),
        Action("pane.up", "To the pane above", ("Ctrl+Alt+ArrowUp",), first=True),
        Action("pane.down", "To the pane below", ("Ctrl+Alt+ArrowDown",), first=True),
        Fixed("Where it was", "The focus goes back to where it was in that pane (Today's notes, "
              "at their caret), else to its first control, the pane's edge lit a moment"),
    ), where="Anywhere: Today's panes, a task's map and page, the sidebar at the left and the "
             "one at the right, the page between them"),
    Scope("writing", "Writing a task", (
        Fixed("[Enter]", "From the title to the description"),
        Fixed("[Ctrl] [Enter]", "Add the task, or save it"),
        Action("writing.openPage", "Editing one in its list: open it on its own page, saved "
               "first (or its Open)", ("Ctrl+Shift+Enter",)),
        Fixed("[Esc]", "Back to the list (an edit saves)"),
        Fixed("[Tab]", "Through the fields; in the description, nests a sub-task"),
        Fixed("[-] [Space]", "In the description, at a line's start: a sub-task ([Shift] [Enter] "
              "writes a note under it)"),
        Action("editor.checklist", "A line into a sub-task; a sub-task ticked, or unticked",
               ("Ctrl+L",)),
        Action("editor.bold", "Bold, in a description or a document", ("Ctrl+B",)),
        Action("editor.italic", "Italic", ("Ctrl+I",)),
        Action("editor.strike", "Struck through", ("Ctrl+Shift+X",)),
        Action("editor.code", "Code", ("Ctrl+`",)),
        Action("editor.reading", "Read it, or write it again (a description, a document, "
               "Today's notes)",
               ("Ctrl+E",)),
        Action("editor.live", "Write it drawn as it reads (Live)", click="[data-md-mode=live]",
               menu=True, words="markdown mode live preview"),
        Action("editor.source", "Write its Markdown (Source)", click="[data-md-mode=source]",
               menu=True, words="markdown mode source raw"),
        Fixed("Markdown", "The description is Markdown (# heading, `code`, [words](link), "
              "> quote), shown as it reads, its marks where the caret is"),
        Fixed("[Ctrl] click", "Opens a link in the description"),
        Fixed("friday [Space]", "Words become fields: today, tomorrow, a weekday, next week; at "
              "3pm, 15:00-16:30; due friday; every day, weekday, week or month; 45m, 1h30, 2 "
              "hours (the estimate); p1 to p4 (the priority, urgent to low)"),
        Fixed("[Backspace]", "Right after, turns them back into words"),
        Fixed("[#] name", "Files it in a project or workstream: [↑] [↓] pick, [Enter] or [Tab] "
              "take it; a few letters of the project's name and the workstream's will do"),
    )),
    Scope("today", "Today", (
        Fixed("[-] [[] []] [Space]", "At a row's start: a task, written in the notes"),
        Fixed("/reflection", "At a row's start: a reflection, free text"),
        Fixed("[Tab]", "From a task's title to the row under it; a row into the task above it, "
              "or into a sub-task"),
        Fixed("[Shift] [Tab]", "A step back out: a sub-task to a row, a row out of its task"),
        Fixed("friday [Space]", "In a task's title, as in the task sheet: words become its "
              "fields (a title's last words as it is closed, the toast saying what they became, "
              "with Undo); Backspace right after, or [Ctrl] [Z] any time, puts the words back"),
        Fixed("[Ctrl] [Enter] or [Esc]", "Close the task (it is added), onto the next row or "
              "where it is"),
        Fixed("[Ctrl] [Enter]", "Close a reflection, onto the next row"),
        Action("today.openTask", "In a task: open it on its own page, added first if it is not "
               "yet (or its Open, after its icons)", ("Ctrl+Shift+Enter",)),
        Fixed("Markdown", "The notes are Markdown, as a task's description is (# heading, "
              "**bold**, `code`, [words](link), - list, > quote), shown as they read, their "
              "marks where the caret is; Live, Source and Reading at the day's header"),
        Action("today.timeline", "Fold the right column away (the timeline, as it starts), the "
               "middle taking its room, or back (in the notes too)", ("Ctrl+\\",),
               click='[data-fold-col="right"]', menu=True, words="timeline fold calendar column"),
        Action("today.plan", "Fold the left column away (the plan and the habits, as it starts), "
               "the middle taking its room, or back (in the notes too)", ("Alt+P",),
               click='[data-fold-col="left"]', menu=True,
               words="plan habits tasks fold pane column"),
        Fixed("[↑] [↓] [←] [→]", "On a pane's grip (its title bar's left edge, Tab reaches it): "
              "the pane up or down its column, or into the column beside it; dragging its "
              "title bar does the same"),
        Fixed("[Delete]", "On a pane's grip: hides the pane (Panes, at the day's header, shows "
              "it again, or sets every pane back as it was)"),
        Action("today.carryAll", "Bring every task of the plan into the day's notes",
               ("Alt+C",), click=".pad-carry-all", menu=True,
               words="carry over yesterday bring all"),
        Action("today.nudge", "Act on the first nudge", click=".nudge-action", menu=True,
               words="nudge reminder"),
        Action("today.dismissNudge", "Dismiss the first nudge", click=".nudge-dismiss", menu=True,
               words="nudge reminder dismiss"),
        Fixed("[Esc]", "Out of the notes (in a task, once it is saved: Esc again)"),
        Fixed("[Space]", "On a habit's box: ticks it done for the day, or unticks it"),
        Fixed("[←] [→]", "On a habit's box: the day before or after, of its last seven, for "
              "the boxes and comments; a click on one of its days does the same"),
        Fixed("[Enter]", "In a habit's comment: saved and closed ([Shift] [Enter], a new line)"),
    ), where="On Today and any day's page"),
    Scope("calendar", "Calendar", (
        Action("calendar.day", "A day", ("D",), click="[data-calendar-view=day]", menu=True,
               words="view"),
        Action("calendar.threeDays", "Three days", ("X",), click="[data-calendar-view='3days']",
               menu=True, words="view 3"),
        Action("calendar.week", "The week", ("W",), click="[data-calendar-view=week]", menu=True,
               words="view"),
        Action("calendar.sheet", "The sheet", ("S",), click="[data-calendar-view=sheet]", menu=True,
               words="view"),
        Action("calendar.date", "Go to a date", ("G",), click="[data-jump-date]", menu=True,
               words="jump pick day"),
        Fixed("[E]", "New event (as anywhere); or draw its time on the grid, or click an hour "
              "there"),
        Fixed("friday [Space]", "In an event's title, words set its day, time and repeat "
              "(\"friday\", \"at 3pm\", \"every week\"); Backspace right after puts them back"),
        Fixed("[Esc]", "Close an event's card or the new event"),
    ), where="On Calendar"),
    Scope("sheet", "Calendar's sheet", (
        Fixed("Arrows", "Cell to cell (outside the sheet, Left and Right step four weeks); with "
              "[Shift], a range"),
        Fixed("Typing or [Enter]", "Write in the cell: where you stay, or a task for the day "
              "(Plan); [Enter] writes it and goes down, [Esc] lets it go"),
        Fixed("[Space]", "Tick a habit done, or accommodation sorted (the range too)"),
        Fixed("Drag", "Down a habit's column (or accommodation's), paints the days it crosses"),
        Action("sheet.fold", "Fold a day to its plan's first line", ("Alt+ArrowLeft",)),
        Action("sheet.unfold", "Open a folded day", ("Alt+ArrowRight",)),
        Action("sheet.foldAll", "Fold every day, or open them all", click="[data-fold-all]",
               menu=True, words="fold collapse expand days"),
        Action("sheet.fillDown", "Fill down from the range's first row (one cell: from the row "
               "above)", ("Ctrl+D",)),
        Fixed("[Ctrl] [C] [V]", "Copy the range; paste from the cursor (one cell fills the "
              "range), a Plan cell's lines as tasks; a spreadsheet's cells paste too"),
        Fixed("[Delete]", "Clear the range's stay, untick its habits and boxes"),
        Fixed("[Ctrl] [Enter]", "Open a Plan cell's first task on its page (as on Projects; or "
              "click its title); writing a task, write it and open it, to write it out"),
    ), where="In the sheet's cells (Calendar, S)"),
    Scope("projects", "Task lists (a project's Tasks, Plan)", (
        Action("list.down", "The next task", ("ArrowDown", "J")),
        Action("list.up", "The task before", ("ArrowUp", "K")),
        Action("list.nextProject", "The next list (a workstream, or a project on Plan)",
               ("Shift+ArrowDown", "Shift+J")),
        Action("list.prevProject", "The list before", ("Shift+ArrowUp", "Shift+K")),
        Fixed("[Home] [End]", "First or last task"),
        Action("task.edit", "Edit", ("Enter", "E")),
        Fixed("[N]", "New task (as anywhere), in the cursor's list where it has its own, else "
              "the page's"),
        Action("task.done", "Done, or not done", ("X",)),
        Action("task.today", "Do today", ("T",)),
        Action("task.tomorrow", "Do tomorrow", ("M",)),
        Action("task.pickDay", "Pick a day, or none", ("D",)),
        Action("task.project", "Project and workstream", ("P",)),
        Action("task.priority", "Priority", ("!",)),
        Action("task.openPage", "Open the cursor's task on its own page (here, on a Gantt and "
               "on Calendar's sheet)", ("Ctrl+Enter",)),
        Action("task.notes", "Show the description; opens Done", ("Space",)),
        Action("task.delete", "Delete, after asking", ("Delete", "Backspace")),
        Fixed("[Esc]", "Leave the list"),
    ), column=2, where="On a project's Tasks and on Plan, with a task in the list focused"),
    Scope("project", "A project's page", (
        Action("project.overview", "Its overview", ("Shift+O",),
               click=".project-tabs a:first-child", menu=True,
               words="project about docs"),
        Action("project.tasks", "Its tasks", ("Shift+T",),
               click=".project-tabs a[href$='/tasks']", menu=True, words="list todo workstreams"),
        Action("project.gantt", "Its Gantt", ("Shift+G",),
               click=".project-tabs a[href$='/gantt']", menu=True, words="timeline chart plan"),
        Fixed("[↑] [↓] [←] [→]", "In its documents: row to row; Right opens a folder, Left folds "
              "it"),
        Action("doc.rename", "In its documents: rename the document or folder", ("F2",)),
        Action("doc.delete", "In its documents: delete the document or folder, after asking",
               ("Delete",)),
    ), column=2, where="On a project's overview, its tasks and its Gantt"),
    Scope("gantt", "A project's Gantt", (
        Fixed("[↑] [↓] [←] [→] or [Tab]", "Move between cells; with Shift, hold a range. Right "
              "from Due goes to the row's own days"),
        Fixed("[Ctrl] [↑] [↓] [←] [→]", "To the end of the bars (or words) the cursor is on, "
              "else the next ones, else the sheet's edge"),
        Fixed("Typing, [Enter] or [F2]", "Write in the cell: a task, a priority (urgent, high, "
              "medium, low, or 1 to 4), W42, 12 Oct or next week, a length (3, 3w, 10d); Enter "
              "keeps it and goes down, Tab across, Esc drops it. On Priority, Enter opens its "
              "menu"),
        Action("gantt.scale", "Weeks or days (outside the sheet's cells)", ("V",), menu=True,
               words="zoom weeks days scale"),
        Action("gantt.show", "Which tasks to show", ("F",), click="[data-gantt-show]", menu=True,
               words="filter status show hide"),
        Action("gantt.shown", "The tasks shown: all, all but done, in progress, review",
               ("Ctrl+Tab",)),
        Action("gantt.shownBack", "The tasks shown, back the other way", ("Ctrl+Shift+Tab",)),
        Action("gantt.workstream", "Add a workstream: write its name, Enter keeps it", ("Alt+W",),
               menu=True, words="add workstream new"),
        Fixed("[Space]", "On the time: the bar over the weeks or days held; on the box: a task to "
              "its next status (in progress, review, done, to do)"),
        Action("gantt.earlier", "Bars a week (or a day) earlier; on a workstream's row, fold it",
               ("Alt+ArrowLeft",)),
        Action("gantt.later", "Bars a week (or a day) later; on a workstream's row, open it",
               ("Alt+ArrowRight",)),
        Action("gantt.endEarlier", "The bars' ends a week (or a day) earlier",
               ("Alt+Shift+ArrowLeft",)),
        Action("gantt.endLater", "The bars' ends a week (or a day) later",
               ("Alt+Shift+ArrowRight",)),
        Action("gantt.rowUp", "The task a row up, into the workstream above; on a workstream's "
               "row, the workstream up", ("Alt+ArrowUp",)),
        Action("gantt.rowDown", "The task a row down, into the workstream below; on a "
               "workstream's row, the workstream down", ("Alt+ArrowDown",)),
        Fixed("Drag", "A task or a workstream by its number"),
        Fixed("[Delete]", "On Task: delete the tasks held, after asking (or a task's bin, on "
              "hover); elsewhere: clear the priorities, bars or dues held"),
        Action("gantt.delete", "Delete the tasks held, or a workstream (its tasks stay), after "
               "asking", ("Ctrl+-", "Ctrl+Delete")),
        Fixed("[Ctrl] [Enter]", "Open the cursor's task on its page (as on Projects; or the "
              "arrow at its Task cell's end, on hover)"),
        Action("gantt.undo", "Undo", ("Ctrl+Z",)),
        Action("gantt.redo", "Redo", ("Ctrl+Y", "Ctrl+Shift+Z")),
        Fixed("[Ctrl] [C] [V]", "Copy cells; paste lines onto Task as new tasks (Task, Priority, "
              "Start, Wks, Due in columns)"),
    ), column=2, where="On a project's Gantt"),
    Scope("task", "A task's page", (
        Fixed("Writing", "Saved as you write, a moment after you pause, and as you leave"),
        Action("save.now", "Save now (a task's page, a document; Ctrl+Enter too, on a task's)",
               ("Ctrl+S",)),
        Fixed("[Esc]", "Save, and step out of the writing"),
        Action("task.page.planned", "Do date", ("Alt+D",),
               click="form.task-sheet[data-sheet=page] [data-prop=planned_for]", menu=True,
               words="day plan schedule"),
        Action("task.page.due", "Due", ("Alt+U",),
               click="form.task-sheet[data-sheet=page] [data-prop=due]", menu=True,
               words="deadline"),
        Action("task.page.repeat", "Repeat", ("Alt+R",),
               click="form.task-sheet[data-sheet=page] [data-prop=repeat]", menu=True,
               words="recurring every"),
        Action("task.page.estimate", "Estimate", ("Alt+E",),
               click="form.task-sheet[data-sheet=page] [data-prop=estimate]", menu=True,
               words="time duration"),
        Action("task.page.priority", "Priority", ("Alt+I",),
               click="form.task-sheet[data-sheet=page] [data-prop=priority]", menu=True,
               words="urgent important"),
        Action("task.page.project", "Project and workstream", ("Alt+P",),
               click="form.task-sheet[data-sheet=page] [data-prop=project]", menu=True,
               words="move workstream"),
        Action("task.page.owner", "Whose task", ("Alt+O",),
               click="form.task-sheet[data-sheet=page] [data-prop=owner]", menu=True,
               words="owner claude assign"),
        Action("task.page.status", "Status", ("Alt+S",),
               click="form.task-sheet[data-sheet=page] [data-prop=status]", menu=True,
               words="done progress review"),
        Action("task.page.history", "How it changed", ("Alt+H",),
               click="form.task-sheet[data-sheet=page] [data-history]", menu=True,
               words="history log"),
    ), column=2, where="On a task's own page"),
    Scope("chat", "Nutrition and Spending", (
        Action("chat.focus", "Write to Claude", ("M",), focus="#chat-composer textarea",
               menu=True, words="message chat claude ask", module=""),
        Fixed("[Enter]", "Send the message to Claude"),
        Fixed("[Shift] [Enter]", "A new line in the message"),
        Action("money.import", "Import a bank statement (Accounts)", ("I",),
               click="form.money-import input[type=file]", menu=True,
               words="csv bank upload statement", module="finances"),
    ), column=2, where="On Nutrition, Spending and Accounts"),
)

ACTIONS: dict[str, Action] = {
    e.id: e for s in SCOPES for e in s.entries if isinstance(e, Action)
}
SCOPE_OF: dict[str, Scope] = {
    e.id: s for s in SCOPES for e in s.entries if isinstance(e, Action)
}


# ---- the keys chosen: keys.toml ----


def keys_file() -> Path:
    """Where the keys chosen are kept: keys.toml in the app's home."""
    return config.HOME / FILE_NAME


@dataclass
class KeyMap:
    """Every action's keys: the defaults, over them the file's, and what in
    the file could not be used (each said, and left out)."""

    keys: dict[str, tuple[str, ...]]
    chosen: dict[str, tuple[str, ...]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    # The file can't be read as TOML: it is not written over.
    broken: bool = False

    def of(self, action_id: str) -> tuple[str, ...]:
        return self.keys.get(action_id, ())

    def text(self, action_id: str) -> str:
        """Its first key in words ("Ctrl+K"), or "" with none."""
        keys = self.of(action_id)
        return text(keys[0]) if keys else ""

    def title(self, words: str, action_id: str) -> str:
        """A control's title with its key: "Search (Ctrl+K)"."""
        key = self.text(action_id)
        return f"{words} ({key})" if key else words

    def aria(self, action_id: str) -> str:
        """Its keys for aria-keyshortcuts: each, space-separated."""
        return " ".join(k.replace("Ctrl+", "Control+") for k in self.of(action_id))

    def slots_are_alt(self) -> bool:
        """The sidebar's pages on Alt+1 to Alt+9, as by default."""
        return all(self.of(f"nav.slot{n}") == (f"Alt+{n}",) for n in range(1, 10))

    def cap(self, action_id: str) -> str:
        """Its first key's last part, as a badge shows it ("1" for Alt+1)."""
        keys = self.of(action_id)
        return shown(keys[0])[-1] if keys else ""

    def hint(self, *action_ids: str) -> Markup:
        """The first keys of a few actions, as a page's hint shows them
        side by side: their modifiers once when they share them
        ("Alt ← →"), else each in full. Empty if one has no key."""
        firsts = [self.of(i)[0] for i in action_ids if self.of(i)]
        if len(firsts) < len(action_ids):
            return Markup("")
        split = [shown(k) for k in firsts]
        mods = {tuple(parts[:-1]) for parts in split}
        cap = Markup("<kbd>{}</kbd>").format
        if len(mods) == 1:
            return Markup("").join([*(cap(m) for m in split[0][:-1]), *(cap(p[-1]) for p in split)])
        return Markup(" ").join(Markup("").join(cap(p) for p in parts) for parts in split)

    def kbd(self, action_id: str) -> Markup:
        """Its keys as key caps, for the keys dialog and the pages' hints."""
        return OR.join(caps(k) for k in self.of(action_id))

    def conflicts(self) -> dict[str, list[str]]:
        """Each action whose key another action in its scope has too: the
        other actions' ids, by action."""
        found: dict[str, list[str]] = {}
        for scope in SCOPES:
            holders: dict[str, list[str]] = {}
            for entry in scope.entries:
                if isinstance(entry, Action) and entry.id in self.keys:
                    for key in self.keys[entry.id]:
                        holders.setdefault(key, []).append(entry.id)
            for ids in holders.values():
                for action_id in ids:
                    others = [i for i in ids if i != action_id]
                    if others:
                        found.setdefault(action_id, [])
                        found[action_id] += [o for o in others if o not in found[action_id]]
        return found


OR = Markup(' <span class="or">or</span> ')


class Current:
    """The keys in use, for the templates: each call asks load(), which
    reads the file again only once it has changed."""

    def __getattr__(self, name: str):  # noqa: ANN204
        return getattr(load(), name)


current = Current()


def caps(combo: str) -> Markup:
    return Markup(" ").join(Markup("<kbd>{}</kbd>").format(part) for part in shown(combo))


def installed_actions() -> dict[str, Action]:
    """The actions of the modules this machine has."""
    settings = config.get_settings()
    return {
        i: a for i, a in ACTIONS.items()
        if (not a.module or settings.installed(a.module))
        and (not SCOPE_OF[i].module or settings.installed(SCOPE_OF[i].module))
    }


def defaults() -> dict[str, tuple[str, ...]]:
    return {i: a.keys for i, a in ACTIONS.items()}


def _read(path: Path) -> tuple[dict, list[str], bool]:
    """The file's [keys] table, what is wrong with it, and whether it can't
    be read at all."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, [], False
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return {}, [f"{FILE_NAME} can't be read ({exc}), so every key is its default"], True
    table = data.get("keys", {})
    if not isinstance(table, dict):
        return {}, [f"{FILE_NAME}: [keys] should be a table of actions and their keys"], False
    return table, [], False


def _keys_of(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    raise DomainError("should be a key, or a list of keys")


_cache: dict[Path, tuple[float, int, KeyMap]] = {}


def load(path: Path | None = None) -> KeyMap:
    """The keys in use now: read again whenever the file changes."""
    path = path or keys_file()
    try:
        stat = path.stat()
        stamp = (stat.st_mtime, stat.st_size)
    except FileNotFoundError:
        stamp = (0.0, -1)
    hit = _cache.get(path)
    if hit and hit[:2] == stamp:
        return hit[2]
    table, problems, broken = _read(path)
    keys = defaults()
    chosen: dict[str, tuple[str, ...]] = {}
    for action_id, value in table.items():
        if action_id not in ACTIONS:
            problems.append(f"{action_id!r} is not an action")
            continue
        try:
            combos = tuple(dict.fromkeys(parse(k) for k in _keys_of(value)))
        except DomainError as exc:
            problems.append(f"{action_id!r} {exc}: it keeps its default")
            continue
        chosen[action_id] = combos
        keys[action_id] = combos
    keymap = KeyMap(keys=keys, chosen=chosen, problems=problems, broken=broken)
    _cache[path] = (*stamp, keymap)
    return keymap


HEADER = """\
# Personal Calendar's keys: the ones chosen over the defaults, an action each.
# Keyboard (Settings, or Ctrl+K "Change the keys") writes this file, and so
# can you, in any text editor: the app reads it again as it changes.
#
#   "app.search" = "Ctrl+P"          one key
#   "task.new" = ["N", "Shift+N"]    several
#   "app.theme" = []                 none
#
# A key: Ctrl, Alt or Shift and then the key, joined by "+": a letter or
# digit, a character such as ? \\ - or a named key (ArrowLeft, Enter, Escape,
# Space, Tab, Delete, Backspace, Home, End, PageUp, PageDown, F1 to F12).
# Every action, its id and its keys: Keyboard, or GET /ui/keys.
"""


def save(action_id: str, combos: list[str] | None, path: Path | None = None) -> KeyMap:
    """An action's keys chosen (None: its default again), kept in the file
    with whatever else is written there, its comments too."""
    path = path or keys_file()
    if action_id not in ACTIONS:
        raise DomainError(f"No action {action_id}")
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        source = HEADER
    try:
        doc = tomlkit.parse(source)
    except TOMLKitError as exc:
        raise DomainError(
            f"{FILE_NAME} can't be read ({exc}): put it right in a text editor first"
        ) from exc
    table = doc.get("keys")
    if table is None:
        table = tomlkit.table()
        doc["keys"] = table
    if combos is None or tuple(parse(c) for c in combos) == ACTIONS[action_id].keys:
        table.pop(action_id, None)
    else:
        keys = list(dict.fromkeys(parse(c) for c in combos))
        table[action_id] = keys[0] if len(keys) == 1 else keys
    _write(path, tomlkit.dumps(doc))
    return load(path)


def reset_all(path: Path | None = None) -> KeyMap:
    """Every key its default again: the file's [keys] emptied, its words kept."""
    path = path or keys_file()
    if not path.exists():
        return load(path)
    try:
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    except TOMLKitError:
        doc = tomlkit.parse(HEADER)
    doc["keys"] = tomlkit.table()
    _write(path, tomlkit.dumps(doc))
    return load(path)


def _write(path: Path, content: str) -> None:
    """Written whole or not at all: a reader never meets half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".keys-", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.write(content)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    # Read again at once, however close in time the last write was.
    _cache.pop(path, None)


# ---- what a page needs: the keys for keys.js, and every action listed ----


def client_map(keymap: KeyMap) -> dict:
    """What keys.js needs: each installed action's keys and how it is done."""
    out = {}
    for action_id, action in installed_actions().items():
        out[action_id] = {
            "keys": list(keymap.of(action_id)),
            "label": action.label,
            "scope": SCOPE_OF[action_id].id,
            **{k: v for k in ("click", "focus", "go", "words") if (v := getattr(action, k))},
            **({"menu": True} if action.menu else {}),
            **({"first": True} if action.first else {}),
        }
    return out


def listing(keymap: KeyMap) -> dict:
    """Every action, its keys and its defaults, by scope: Keyboard's page,
    and GET /ui/keys."""
    installed = installed_actions()
    conflicts = keymap.conflicts()
    scopes = []
    for scope in SCOPES:
        entries = []
        for entry in scope.entries:
            if isinstance(entry, Fixed):
                entries.append({"fixed": True, "keys": entry.keys, "label": entry.label})
            elif entry.id in installed:
                entries.append({
                    "id": entry.id,
                    "label": entry.label,
                    "keys": list(keymap.of(entry.id)),
                    "default": list(entry.keys),
                    "changed": entry.id in keymap.chosen,
                    "conflicts": [
                        {"id": other, "label": ACTIONS[other].label}
                        for other in conflicts.get(entry.id, [])
                    ],
                })
        if entries:
            scopes.append({
                "id": scope.id, "title": scope.title, "where": scope.where,
                "column": scope.column, "entries": entries,
            })
    return {"file": str(keys_file()), "problems": keymap.problems, "broken": keymap.broken,
            "changed": len(keymap.chosen), "scopes": scopes}


# [Key]: a key cap, ending where a word, a mark or the next cap goes on
# ("[Ctrl][Enter]"), so "[[]" and "[- [ ]]" are caps too.
_CAP = re.compile(r"\[(.+?)\](?=[\s,;.)\[]|$)")


def with_caps(words: str) -> Markup:
    """Words with [Key] in them, each such key a key cap."""
    return Markup(_CAP.sub(lambda m: f"<kbd>{m.group(1)}</kbd>", str(escape(words))))


def fixed_keys(words: str) -> Markup:
    """A fixed entry's keys as the dialog shows them: [Key] a key cap, "or"
    between keys that do the same."""
    return OR.join(with_caps(part) for part in re.split(r"\s+or\s+", words))


def main() -> None:
    keymap = load()
    print(f"Keys: {keys_file()}")
    for problem in keymap.problems:
        print(f"  ! {problem}")
    for scope in SCOPES:
        print(f"\n{scope.title}")
        for entry in scope.entries:
            if isinstance(entry, Action):
                keys = ", ".join(keymap.of(entry.id)) or "(none)"
                mark = " *" if entry.id in keymap.chosen else ""
                print(f"  {entry.id:<22} {keys:<28}{mark} {entry.label}")


if __name__ == "__main__":
    main()
