"""Board, a view of a project's Tasks tab (partials/project_tasks/board.html):
a column a workstream, a card a task, drawn by the server; a card drawn
again in it (a tick, an edit closed) comes back as a card."""

import re
from datetime import date, timedelta

from app.models import TaskOwner, TaskPriority, TaskStatus, WorkstreamStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()
BOARD = {"X-Tasks-View": "board"}


def board(client, project_id: int) -> str:
    page = client.get(f"/projects/{project_id}/tasks?view=board")
    assert page.status_code == 200
    return page.text


def column(page: str, column_id: str) -> str:
    """A column's markup, from its section to the next one's."""
    start = page.rindex("<section", 0, page.index(f'id="{column_id}"'))
    end = page.find("<section", start + 1)
    return page[start : end if end != -1 else len(page)]


def titles(part: str) -> list[str]:
    return re.findall(r'class="task-row board-card[^"]*"[^>]*data-task-title="([^"]*)"', part)


def card(part: str, task_id: int) -> str:
    """One card's markup, its <li> whole (its sub-tasks' items inside it)."""
    start = part.rindex("<li", 0, part.index(f'id="task-{task_id}"'))
    end = part.index("\n</li>", start)
    return part[start : end + 6]


def test_a_column_a_workstream_then_the_tasks_in_none(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    sync = projects_svc.create_workstream(db, project_id=project.id, name="Sync engine")
    empty = projects_svc.create_workstream(db, project_id=project.id, name="Polish")
    tasks_svc.create_task(db, title="parse", project_id=project.id, workstream_id=sync.id)
    tasks_svc.create_task(
        db, title="write", project_id=project.id, workstream_id=sync.id, planned_for=TODAY
    )
    shipped = tasks_svc.create_task(db, title="ship", project_id=project.id, workstream_id=sync.id)
    tasks_svc.set_status(db, shipped.id, TaskStatus.done)
    tasks_svc.create_task(db, title="loose end", project_id=project.id)
    page = board(client, project.id)

    assert 'class="task-lists tasks-in-board"' in page
    # Each workstream in order, its open tasks soonest first, how far it is
    # (done of all, in figures and a bar), and a composer filing into it.
    one = column(page, f"workstream-group-{sync.id}")
    assert f'data-file-workstream="{sync.id}"' in one
    assert ">Sync engine</h2>" in one and titles(one) == ["write", "parse"]
    assert '<span class="count" aria-hidden="true">1/3</span>' in one
    assert 'aria-label="1 of 3 done"' in one and "width: 33.3%" in one
    assert f'data-composer-key="workstream-tasks-{sync.id}"' in one
    assert f'name="workstream_id" value="{sync.id}"' in one
    # An open workstream with nothing in it yet keeps its column, with no bar.
    two = column(page, f"workstream-group-{empty.id}")
    assert titles(two) == [] and "tv-meter" not in two
    assert page.index(f"workstream-group-{sync.id}") < page.index(f"workstream-group-{empty.id}")
    # Then the tasks in none, filing into the project.
    loose = column(page, "board-loose")
    assert ">No workstream</h2>" in loose and titles(loose) == ["loose end"]
    assert '<span class="count">1</span>' in loose
    assert f'data-file-project="{project.id}"' in loose and "board-spare" not in loose
    assert f'data-composer-key="project-tasks-{project.id}"' in loose
    # The page's own new-workstream line gives way to the board's last column.
    new = column(page, "board-new")
    assert f'hx-post="/ui/projects/{project.id}/workstreams"' in new


def test_no_workstream_is_spare_while_empty_and_the_only_column_with_none(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    tasks_svc.create_task(db, title="parse", project_id=project.id)
    # No workstreams: one column, Tasks, always there.
    page = board(client, project.id)
    assert ">Tasks</h2>" in column(page, "board-loose")
    assert "board-spare" not in column(page, "board-loose")

    ws = projects_svc.create_workstream(db, project_id=project.id, name="Sync engine")
    for task in tasks_svc.list_tasks(db, project_id=project.id):
        tasks_svc.update_task(db, task.id, workstream_id=ws.id)
    # Workstreams, and none of the tasks in none: drawn, shown only while a
    # card is in hand, to take it out of its workstream.
    loose = column(board(client, project.id), "board-loose")
    assert "board-spare" in loose and ">No workstream</h2>" in loose and titles(loose) == []
    assert 'class="count"' not in loose  # no "0" while it shows, a card in hand


def test_a_card_carries_what_the_task_has(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    task = tasks_svc.create_task(
        db,
        title="parse the feed",
        project_id=project.id,
        owner=TaskOwner.claude,
        priority=TaskPriority.high,
        estimate_minutes=90,
        planned_for=TODAY,
        due=TODAY + timedelta(days=2),
        notes="Context\n- [x] fetch\n- [ ] parse",
    )
    late = tasks_svc.create_task(
        db, title="overdue", project_id=project.id, due=TODAY - timedelta(days=1)
    )
    later = tasks_svc.create_task(
        db, title="later", project_id=project.id, due=TODAY + timedelta(days=30)
    )
    page = board(client, project.id)
    one = card(page, task.id)

    assert f'data-task-id="{task.id}" data-task-title="parse the feed" tabindex="-1"' in one
    assert 'class="task-check"' in one and 'class="task-title-btn"' in one
    assert '<span class="chip tv-chip queued">Queued</span>' in one
    assert 'data-priority="high" title="Priority: High"' in one
    # Its sub-tasks' count shows its description under the card.
    assert f'aria-controls="board-notes-{task.id}"' in one and "1/2" in one
    assert f'id="board-notes-{task.id}" hidden' in one and "Context" in one
    assert '<span class="tv-estimate" title="Estimate">1h 30m</span>' in one
    # Its days at the right: the do-date, then the deadline, with its word.
    assert '<span class="tv-date">today</span>' in one
    assert re.search(r'<span class="tv-due chip warn">due \w{3} \d', one)
    # Its quick do-dates (not today, which it has) and its page.
    assert 'data-plan="tomorrow"' in one and 'data-plan="today"' not in one
    assert "data-pick-date" in one and f'href="/tasks/{task.id}"' in one
    assert "task-delete" not in one  # Delete is the card's key alone (tasks.js)

    assert '<span class="tv-due chip err">due yesterday</span>' in card(page, late.id)
    assert re.search(r'<span class="tv-due">due \w{3} \d', card(page, later.id))
    # Notes alone: their mark opens them.
    noted = tasks_svc.create_task(db, title="noted", project_id=project.id, notes="Why")
    plain = tasks_svc.create_task(db, title="plain", project_id=project.id)
    page = board(client, project.id)
    assert f'aria-controls="board-notes-{noted.id}" aria-label="It has notes: show them"' in (
        card(page, noted.id)
    )
    # Nothing to carry: no line under its title.
    assert "board-meta" not in card(page, plain.id)


def test_the_finished_work_waits_behind_show_completed(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    done_ws = projects_svc.create_workstream(db, project_id=project.id, name="Spike")
    projects_svc.update_workstream(db, done_ws.id, status=WorkstreamStatus.done)
    finished = tasks_svc.create_task(db, title="fetched", project_id=project.id)
    tasks_svc.set_status(db, finished.id, TaskStatus.done)
    page = board(client, project.id)

    assert 'id="tasks-show-done-box" data-show-done>' in page
    assert 'Show completed <span class="count">1</span>' in page
    done = column(page, "board-done")
    assert "data-done-part hidden" in done
    assert titles(done) == ["fetched"]
    assert 'class="task-row board-card done"' in done and "checked" in done
    # A finished workstream is a row there, which opens it again.
    assert "Finished workstreams" in done and ">Spike</span>" in done
    assert f'hx-post="/ui/workstreams/{done_ws.id}/toggle"' in done
    # Nothing finished: no column for it, and Show completed only keeps its place.
    other = board(client, projects_svc.create_project(db, name="Garden").id)
    assert 'id="board-done"' not in other and 'id="tasks-show-done" data-none' in other


def test_a_card_drawn_again_is_the_card_the_board_draws(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    task = tasks_svc.create_task(
        db, title="parse", project_id=project.id, notes="- [ ] fetch", planned_for=TODAY
    )
    drawn = card(board(client, project.id), task.id)
    again = client.get(f"/ui/tasks/{task.id}/row", headers=BOARD).text.strip()
    assert again == drawn

    # Ticked, it comes back a card, done; a sub-task ticked, with its sub-tasks shown.
    ticked = client.post(f"/ui/tasks/{task.id}/toggle", headers=BOARD).text.strip()
    assert ticked.startswith('<li class="task-row board-card done"')
    assert ticked.count('<li class="task-row') == 1
    sub = client.post(
        f"/ui/tasks/{task.id}/subtasks/0/toggle", data={"text": "fetch"}, headers=BOARD
    ).text
    assert f'id="board-notes-{task.id}">' in sub  # shown, not hidden

    # Added from a column's composer, it joins the column as a card.
    added = client.post(
        "/ui/tasks/quick-add",
        data={"title": "write", "project_id": str(project.id)},
        headers=BOARD,
    ).text.strip()
    assert added.startswith('<li class="task-row board-card"')


def test_a_workstream_finished_by_its_tasks_keeps_its_column_until_marked_done(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    first = projects_svc.create_workstream(db, project_id=project.id, name="Research")
    middle = projects_svc.create_workstream(db, project_id=project.id, name="Build")
    last = projects_svc.create_workstream(db, project_id=project.id, name="Ship")
    for ws in (first, last):
        tasks_svc.create_task(
            db, title=f"{ws.name} open", project_id=project.id, workstream_id=ws.id
        )
    built = tasks_svc.create_task(db, title="built", project_id=project.id, workstream_id=middle.id)
    tasks_svc.set_status(db, built.id, TaskStatus.done)
    page = board(client, project.id)

    # Its last task ticked, it stays in its place, empty, its bar full.
    ids = [f"workstream-group-{ws.id}" for ws in (first, middle, last)]
    assert [page.index(i) for i in ids] == sorted(page.index(i) for i in ids)
    build = column(page, ids[1])
    assert titles(build) == [] and 'aria-label="1 of 1 done"' in build and "width: 100.0%" in build
    assert ">Build</span>" not in column(page, "board-done")

    # Marked done, it goes to Done's finished workstreams.
    projects_svc.update_workstream(db, middle.id, status=WorkstreamStatus.done)
    page = board(client, project.id)
    assert ids[1] not in page
    assert ">Build</span>" in column(page, "board-done")
