"""By do-date, a view of a project's Tasks tab (partials/project_tasks/
schedule.html), as the server draws it: a section for each stretch of days,
the open tasks in theirs, each a row of cells; the day a task dropped on a
section takes, and its composer's; and the row drawn again in the view."""

from datetime import date, timedelta

from app.models import TaskPriority, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()
VIEW = {"X-Tasks-View": "schedule"}


def day(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def sections(page: str) -> dict[str, str]:
    """The view's sections by key ("today", "done", ...), each its markup."""
    view = page.split('class="tv-grid"')[1].split('class="list-section new-workstream"')[0]
    parts = view.split('<section class="tv-section')[1:]
    return {part.split('id="sv-')[1].split('"')[0]: part.split("</section>")[0] for part in parts}


def row(markup: str, task_id: int) -> str:
    """A task's row, from its line to its end."""
    return markup.split(f'id="task-{task_id}"')[1].split("\n</li>")[0]


def test_the_open_tasks_are_in_a_section_by_when_they_are_to_be_done(client, db) -> None:
    project = projects_svc.create_project(db, name="Reno")
    made = {
        title: tasks_svc.create_task(db, title=title, project_id=project.id, planned_for=planned)
        for title, planned in [
            ("late", day(-3)),
            ("now", TODAY),
            ("next", day(1)),
            ("soon", day(7)),
            ("far", day(8)),
            ("someday", None),
        ]
    }
    finished = tasks_svc.create_task(
        db, title="measured", project_id=project.id, planned_for=day(-1)
    )
    tasks_svc.set_status(db, finished.id, TaskStatus.done)

    page = client.get(f"/projects/{project.id}/tasks?view=schedule").text
    found = sections(page)
    assert list(found) == ["overdue", "today", "tomorrow", "week", "later", "none", "done"]
    for key, title in [
        ("overdue", "late"),
        ("today", "now"),
        ("tomorrow", "next"),
        ("week", "soon"),
        ("later", "far"),
        ("none", "someday"),
    ]:
        assert f'data-task-title="{title}"' in found[key]
        others = [t for t in made if t != title]
        assert not any(f'data-task-title="{t}"' in found[key] for t in others)
    # The last two weeks' finished work, shown only while Show completed is ticked.
    assert (
        "data-done-part hidden" in found["done"] and 'data-task-title="measured"' in found["done"]
    )
    assert "data-show-done" in page.split('id="project-tasks"')[0]
    # Each a list section to the keyboard, folding on its own.
    assert 'data-fold-key="when-today"' in found["today"] and 'class="tv-fold"' in found["today"]
    assert ">Overdue</h2>" in found["overdue"]


def test_a_section_says_the_day_a_task_dropped_on_it_takes(client, db) -> None:
    project = projects_svc.create_project(db, name="Reno")
    page = client.get(f"/projects/{project.id}/tasks?view=schedule").text
    found = sections(page)
    # Nothing overdue: no Overdue section; nothing finished: no Completed, and
    # Show completed only keeps its place. Empty ones stay, to drop on.
    assert list(found) == ["today", "tomorrow", "week", "later", "none"]
    assert 'id="tasks-show-done" data-none' in page
    # Its day in days from today, worked out where it is dropped.
    drops = {key: found[key].split('data-drop-offset="')[1].split('"')[0] for key in found}
    assert drops == {"today": "0", "tomorrow": "1", "week": "2", "later": "8", "none": ""}
    for key in found:
        assert "sv-empty" in found[key].split(">")[0]
    # A stretch of days says which day a task held over it would take.
    assert "data-drop-note" in found["week"] and "data-drop-note" in found["later"]
    assert "data-drop-note" not in found["today"]


def test_only_a_section_with_something_in_it_folds(client, db) -> None:
    project = projects_svc.create_project(db, name="Reno")
    tasks_svc.create_task(db, title="soon", project_id=project.id, planned_for=day(3))
    found = sections(client.get(f"/projects/{project.id}/tasks?view=schedule").text)
    # Its rows, or its composer: a chevron, and a fold kept by its key.
    for key in ("today", "tomorrow", "week", "none"):
        head = found[key].split(">")[0]
        assert f'data-fold-key="when-{key}"' in head and 'class="tv-fold"' in found[key]
    # Nothing in it and nothing to write in it: no chevron, its place kept.
    assert "data-fold-key" not in found["later"].split(">")[0]
    assert "data-fold" not in found["later"]
    assert '<span class="tv-fold" aria-hidden="true"></span>' in found["later"]


def test_overdue_takes_no_drop(client, db) -> None:
    project = projects_svc.create_project(db, name="Reno")
    tasks_svc.create_task(db, title="late", project_id=project.id, planned_for=day(-1))
    overdue = sections(client.get(f"/projects/{project.id}/tasks?view=schedule").text)["overdue"]
    assert "data-drop-offset" not in overdue.split(">")[0]
    assert "sv-empty" not in overdue.split(">")[0]


def test_today_tomorrow_and_none_write_tasks_dated_as_they_are(client, db) -> None:
    project = projects_svc.create_project(db, name="Reno")
    found = sections(client.get(f"/projects/{project.id}/tasks?view=schedule").text)
    for key, planned in [("today", TODAY), ("tomorrow", day(1)), ("none", None)]:
        composer = found[key].split('class="compose-slot"')[1]
        assert f'data-composer-key="sv-rows-{key}"' in composer
        assert f'hx-target="#sv-rows-{key}"' in composer
        value = planned.isoformat() if planned else ""
        assert f'name="planned_for" value="{value}"' in composer
        # A task dated away from the list it is written in regroups the page.
        assert f'name="list_day" value="{value or "none"}"' in composer
        assert f'id="sv-rows-{key}"' in found[key]
    assert "Add task for today" in found["today"]
    for key in ("week", "later"):
        assert "compose-slot" not in found[key]


def test_a_row_is_a_line_of_cells(client, db) -> None:
    project = projects_svc.create_project(db, name="Reno")
    lane = projects_svc.create_workstream(db, project_id=project.id, name="Quotes and permits")
    task = tasks_svc.create_task(
        db,
        title="call the sparky",
        project_id=project.id,
        workstream_id=lane.id,
        planned_for=day(3),
        due=day(1),
        estimate_minutes=90,
        priority=TaskPriority.high,
        notes="- [x] find a number\n- [ ] ring",
    )
    page = client.get(f"/projects/{project.id}/tasks?view=schedule").text
    week = sections(page)["week"]
    drawn = row(week, task.id)
    # An open row is dragged to another day (tasks.js arms it, in a section a drop dates).
    assert 'data-drop-offset="2"' in week.split(">")[0]
    assert '<span class="visually-hidden">Workstream </span>Quotes and permits' in drawn
    planned = f"{day(3).strftime('%a')} {day(3).day}"
    assert f'<span class="tv-date"><span class="tv-cap">{planned}' in drawn
    assert '<span class="visually-hidden">Due </span><span class="tv-due chip warn">' in drawn
    assert 'data-priority="high"' in drawn and ">High</span>" in drawn
    assert '<span class="visually-hidden">Estimate </span>' in drawn and ">1h 30m</span>" in drawn
    # Its sub-tasks: a count that shows them, under the line, hidden till then.
    assert f'aria-controls="tv-subtasks-{task.id}"' in drawn and "1/2" in drawn
    assert f'id="tv-subtasks-{task.id}" hidden' in drawn and ">ring</span>" in drawn
    # Its quick do-dates and its page; Delete is the row's key alone (tasks.js).
    assert 'data-plan="today"' in drawn and 'data-plan="tomorrow"' in drawn
    assert f'href="/tasks/{task.id}"' in drawn and "task-delete" not in drawn


def test_a_row_drawn_again_in_the_view_is_its_row(client, db) -> None:
    project = projects_svc.create_project(db, name="Reno")
    task = tasks_svc.create_task(
        db, title="ring", project_id=project.id, notes="- [ ] one\n- [ ] two"
    )
    again = client.get(f"/ui/tasks/{task.id}/row", headers=VIEW).text
    assert again.lstrip().startswith(f'<li class="task-row tv-row" id="task-{task.id}"')
    # Ticked, it comes back done, with no do-dates.
    done = client.post(f"/ui/tasks/{task.id}/toggle", headers=VIEW).text
    assert 'class="task-row tv-row done"' in done
    assert "task-plan" not in done
    # A sub-task ticked: the row back with its sub-tasks still shown.
    client.post(f"/ui/tasks/{task.id}/toggle", headers=VIEW)
    ticked = client.post(
        f"/ui/tasks/{task.id}/subtasks/0/toggle", data={"text": "one"}, headers=VIEW
    ).text
    assert f'id="tv-subtasks-{task.id}">' in ticked and 'aria-expanded="true"' in ticked
    assert "1/2" in ticked


def test_a_task_without_cells_draws_empty_ones(client, db) -> None:
    project = projects_svc.create_project(db, name="Reno")
    task = tasks_svc.create_task(db, title="bare", project_id=project.id)
    drawn = row(client.get(f"/ui/tasks/{task.id}/row", headers=VIEW).text, task.id)
    # Empty cells are empty, so a narrow screen leaves them out of the line under the title.
    for cell in ("sv-ws", "sv-do", "sv-due", "sv-prio", "sv-est"):
        assert f'<div class="tv-cell {cell}"></div>' in drawn
