# ruff: noqa: E501  (the README's Markdown keeps a sentence a line, however long)
"""README.md at the everyday files' top (SPEC.md, Files first): what is
where, how each file reads, what the database holds and how to query it,
and how to change what the files only show. For an agent (or a person)
landing in the folder with nothing else to go on. The app's: written again
as it starts, from the code (its tables from the models), so it never
drifts from what the app does.
"""

from __future__ import annotations

from sqlalchemy import Table

from app.config import get_settings
from app.db import Base
from app.services import everyday

FILE = "README.md"

# The planner's tables, as the README describes them, in this order.
TABLES = {
    "projects": "A project: its name, status (active, paused, done), colour, folder "
    "(its folder's name in projects/). Its about (`notes`) is project.md's words.",
    "workstreams": "A lane of a project's tasks: name, status (open, done), position.",
    "project_repos": "A repository a project's work lives in (project.toml's `repos`).",
    "tasks": "A task: its fields (the database's: status, owner, project, workstream, "
    "dates, estimate, priority, position) and its words (`notes`, `acceptance`, "
    "`outcome`: task.md's, kept here too for lists and search).",
    "task_repos": "The repositories a task is worked in.",
    "task_pull_requests": "A task's pull requests, as GitHub last had them.",
    "task_runs": "A task launched as an agent run: runner, branch, workspace, state.",
    "task_updates": "What was reported of a task's work as it went: when, who, a note.",
    "task_revisions": "Every change to a task, the task as it stood after it, and who "
    "made it (oscar, claude, agent, system, or file).",
    "notebook_pages": "A day's page: its blocks (the day's file read in), version.",
    "habits": "A habit: its name (its file's, habits/<name>.md), its days (the weekdays "
    "it is due, Monday 0 to Sunday 6; empty for any day), what it is (`notes`: its "
    "file's words above its log).",
    "habit_checks": "A habit on a day: done (ticked), or skipped (not ticked, with a "
    "comment); its note is the day's comment, its file's log entry.",
    "events": "A calendar event: title, start, end, source (local, work).",
    "recurrence_templates": "A repeating task's or event's rule.",
    "documents": "Every Markdown file here, as the app last read it: whose it is "
    "(`owner`: task:12, project:3, notebook, habit:4), its path, its version.",
    "documents_fts": "Their words, for full-text search (SQLite FTS5): "
    "`SELECT d.path FROM documents_fts f JOIN documents d ON d.id = f.rowid "
    "WHERE documents_fts MATCH 'word*'`.",
    "document_revisions": "Every file's history but a task.md's (a task's is "
    "task_revisions): whose, its path there, when, who, its words.",
}


def _columns(name: str) -> str:
    table = Base.metadata.tables.get(name)
    if not isinstance(table, Table):
        return ""
    return ", ".join(f"`{c.name}`" for c in table.columns)


def text() -> str:
    settings = get_settings()
    root = everyday.root()
    url = f"http://127.0.0.1:{settings.server.port}"
    tables = "\n".join(
        f"- **{name}**: {about}" + (f"\n  Columns: {cols}." if (cols := _columns(name)) else "")
        for name, about in TABLES.items()
    )
    return f"""# The everyday files

Oscar's planner, Personal Calendar, keeps here everything written in it, as Markdown: the master copy.
Read it, grep it, write it: the app reads what changes here a moment after it does.
This file is the app's, written again as it starts; an edit here does not last.

The rule: **words are files, fields and records are rows.**
What Oscar or an agent writes is a file here.
What the app keeps track of (a task's status, dates, owner, project; events, habits, pull requests, runs, history) is the database's, and shows in the files as front matter the app writes.

## What is where

```
{root}
  README.md                       this file
  projects/<project>/             a project
    project.md                    the project: front matter (the app's), then its about
    project.toml                  its id, and its repositories (`repos`, yours to edit)
    AGENTS.md                     what an agent working on it reads first
    <documents>.md, <folders>/    its other documents: its context
    tasks/<id>-<title>/           a task of the project
      task.md                     the task: front matter (the app's), description, ## Acceptance, ## Outcome
      <files>.md, <folders>/      its other files: plans, research, notes
  tasks/<id>-<title>/             a task in no project, as above
  notebook/<year>/<day>.md        a day's notes
  habits/<name>.md                a habit: front matter (the app's), what it is, then ## Log
  repos/                         each repository's main clone
  work/                           the folders agent runs work in
  .trash/                         the folders of tasks deleted
```

Folders follow the database: a task moved to another project, or renamed, has its folder moved; a project renamed has its folder renamed.
Find a task by its id: `{root.as_posix()}/projects/*/tasks/12-*` or `{root.as_posix()}/tasks/12-*`.

## How each file reads

- **task.md**: its front matter is the app's (id, title, status, owner, project, workstream, priority, planned_for, due, starts_on, estimate_minutes, repos, pull_requests): an edit there is put back.
  Then the description, in Markdown as GitHub reads it: `- [ ] ` lines are its sub-tasks (`- [x] ` done), `- ` lines plain bullets.
  Then `## Acceptance` (what done means) and `## Outcome` (what came of it), always both, last.
  The description, acceptance and outcome are the file's: write them here and the task has them.
- **A new task**: make a folder in a project's `tasks/` (or the top `tasks/`) holding a task.md, its front matter at least a `title`; the app makes it a task (its folder then takes its id).
- **project.md**: front matter the app's (id, name, status, workstreams, repos), then the project's about, the file's.
- **notebook/<year>/<day>.md**: the day's notes as Oscar writes them in the app: rows; `- [ ] ` rows are tasks, their tabbed rows under them their description, a task's row ending in `<!-- task:<id> -->` (the task it made); `/reflection` a reflection, its other rows tabbed in.
  Where he stays each day is not in the notes: it is fields, the database's, read through `get_notebook`.
- **habits/<name>.md**: a habit, named by its file (lower case, hyphens: `morning-skin-care.md`).
  Its front matter is the app's (id, name, days, since): an edit there is put back.
  Then what the habit is, why and how, then `## Log`: a comment a day, the newest first, `- 2026-10-20: words`, its other lines indented under it.
  Whether a day was done is the database's (`habit_checks`), ticked in the app; a comment on a day not ticked says why it was skipped.
  The words are the file's: write them here and the habit has them; a new file here, its name a habit's, is a new habit.
- **AGENTS.md and the other documents**: Markdown, as written.

## Changing what the files only show

Fields change in the app, over its HTTP API (JSON bodies, no sign-in, on this machine) or through Claude's MCP tools (`{url}/mcp`).

- `GET {url}/api/tasks`, `GET {url}/api/tasks/<id>`: tasks, with `files_folder` and `task_file`.
- `POST {url}/api/tasks` with `{{"title": "...", "project_id": 3}}`: a new task.
- `PATCH {url}/api/tasks/<id>` with any of `title`, `status`, `owner`, `project_id`, `workstream_id`, `planned_for`, `due`, `starts_on`, `estimate_minutes`, `priority`, `repos`.
- `POST {url}/api/tasks/<id>/report` with any of `status` (in_progress, blocked, needs_review; never done), `note`, `outcome`, `pull_requests` (their URLs): an agent's word on its task.
- `GET {url}/api/projects`, `GET {url}/api/projects/<id>/context`.
- The whole API: `{url}/api/docs`.

A task is done when its pull requests merge, or when Oscar says so: never by an agent.

## The database

SQLite, one file: `{settings.db_path}`.
Read it with `sqlite3` (open it read-only: `sqlite3 "file:{settings.db_path.as_posix()}?mode=ro" -cmd ".tables"`); write through the app, which keeps its rules and these files in step.
Dates are calendar dates (YYYY-MM-DD), times naive local wall time.
The planner's tables:

{tables}

Health, finances and code (Garmin, money, repositories) have tables of their own, outside this folder.
"""


def write() -> None:
    """README.md written, when its words are not already."""
    path = everyday.root() / FILE
    words = text()
    try:
        if everyday.read_text(path) == words:
            return
    except FileNotFoundError:
        pass
    everyday.write_text(path, words)
