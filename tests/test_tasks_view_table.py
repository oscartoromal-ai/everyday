"""The Tasks tab's Table (partials/project_tasks/table.html), as the server
draws it: the columns, a section a workstream and then the tasks in none,
each task a line of cells, the finished work kept for Show completed; and
a task's row drawn again in it (table_row.html)."""

from datetime import date, timedelta

from app.models import TaskOwner, TaskPriority, TaskStatus, WorkstreamStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()
TABLE = {"X-Tasks-View": "table"}


def table(client, project_id: int) -> str:
    page = client.get(f"/projects/{project_id}/tasks?view=table")
    assert page.status_code == 200
    return page.text.split('id="project-tasks"')[1].split('class="list-section new-workstream"')[0]


def part(html: str, start: str, end: str = "</section>") -> str:
    """The piece of html from `start` to the next `end`."""
    return start + html.split(start, 1)[1].split(end, 1)[0]


def row_of(html: str, task_id: int) -> str:
    return part(html, f'id="task-{task_id}"', "\n</li>")


def test_the_table_names_its_columns_and_draws_a_section_a_workstream(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    api = projects_svc.create_workstream(db, project_id=project.id, name="API")
    ui = projects_svc.create_workstream(db, project_id=project.id, name="UI")
    parse = tasks_svc.create_task(db, title="parse", project_id=project.id, workstream_id=api.id)
    tasks_svc.create_task(db, title="fetch", project_id=project.id, workstream_id=api.id)
    tasks_svc.set_status(db, parse.id, TaskStatus.done)
    loose = tasks_svc.create_task(db, title="tidy", project_id=project.id)
    html = table(client, project.id)

    columns = part(html, 'class="tv-line tv-columns"', "</div>\n  </div>")
    names = ["Task name", "Do-date", "Due", "Priority", "Estimate", "Owner"]
    assert [n for n in names if n in columns] == names
    # A section a workstream, in the project's order, then the tasks in none.
    assert html.index('id="tt-ws-' + str(api.id)) < html.index(f'id="tt-ws-{ui.id}"')
    assert html.index(f'id="tt-ws-{ui.id}"') < html.index('id="tt-none"')
    api_part = part(html, f'id="tt-ws-{api.id}"')
    assert 'data-file-workstream="' + str(api.id) in api_part
    assert (
        ">API</h2>" in api_part and 'aria-label="1 of 2 done"' in api_part and ">1/2<" in api_part
    )
    assert "fetch" in api_part and "tidy" not in api_part
    # A workstream with no open task still has its section and its composer.
    ui_part = part(html, f'id="tt-ws-{ui.id}"')
    assert "data-composer" in ui_part and 'class="task-row' not in ui_part
    none_part = part(html, 'id="tt-none"')
    assert ">No workstream</h2>" in none_part and f'id="task-{loose.id}"' in none_part
    assert f'data-file-project="{project.id}"' in none_part


def test_a_project_without_workstreams_has_its_tasks_under_tasks(client, db) -> None:
    project = projects_svc.create_project(db, name="Garden")
    tasks_svc.create_task(db, title="mow", project_id=project.id)
    html = table(client, project.id)
    assert ">Tasks</h2>" in html and "No workstream" not in html
    assert 'id="tt-ws-' not in html


def test_a_task_is_a_line_of_cells(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    task = tasks_svc.create_task(
        db,
        title="parse the feed",
        project_id=project.id,
        planned_for=TODAY - timedelta(days=1),
        due=TODAY + timedelta(days=1),
        priority=TaskPriority.high,
        estimate_minutes=90,
        notes="Context\n- [x] read\n- [ ] write\n- a bullet",
    )
    claude = tasks_svc.create_task(
        db,
        title="review",
        project_id=project.id,
        owner=TaskOwner.claude,
        status=TaskStatus.needs_review,
    )
    html = table(client, project.id)

    row = row_of(html, task.id)
    assert row.count('class="tv-cell') == 6
    assert 'class="task-check"' in row and 'class="task-title-btn"' in row
    assert 'title="parse the feed"' in row  # whole on hover, where the line cuts it
    # Its dates as a column reads them: a do-date past is plain (Overdue
    # says so where it matters), a deadline soon a warn badge.
    assert 'class="tv-date"><span class="tv-cap">yesterday<' in row
    assert 'class="tv-due chip warn"><span class="tv-cap">tomorrow<' in row
    assert 'data-priority="high"' in row and ">High<" in row
    assert ">1h 30m<" in row
    # Each cell says its column to a reader.
    for name in ("Do-date", "Due", "Priority", "Estimate"):
        assert f'<span class="visually-hidden">{name} </span>' in row
    # Oscar's own tasks go unsaid in Owner.
    assert "Oscar" not in row and "tv-owner" not in row
    # Its sub-tasks: the count, and the chevron that shows them under the line.
    assert "1/2" in row and "data-subtasks" in row
    assert f'aria-controls="tv-subtasks-{task.id}"' in row
    subtasks = part(row, f'id="tv-subtasks-{task.id}"', "</ul>")
    assert " hidden>" in subtasks.split("\n")[0]
    assert "read" in subtasks and "write" in subtasks and "a bullet" not in subtasks
    # Its quick do-dates and its page, for the hover.
    assert 'data-plan="today"' in row and 'data-plan="tomorrow"' in row and "data-pick-date" in row
    assert f'href="/tasks/{task.id}"' in row
    # The keys' row: the cursor's stop, named for Delete's question (tasks.js).
    assert 'tabindex="-1"' in row and 'data-task-title="parse the feed"' in row
    assert "task-delete" not in row
    # Claude's task names how its run stands after its title, where every
    # width keeps it, and Claude in Owner.
    claude_row = row_of(html, claude.id)
    name = part(claude_row, 'class="tv-cell tv-name"', 'class="tv-cell tt-wide"')
    assert "Needs review" in name and 'class="tv-avatar claude"' in claude_row


def test_finished_work_waits_for_show_completed(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    task = tasks_svc.create_task(db, title="parse", project_id=project.id)
    assert "data-done-part" not in table(client, project.id)
    tasks_svc.set_status(db, task.id, TaskStatus.done)
    html = table(client, project.id)
    done = part(html, 'id="tt-done"')
    assert "data-done-part hidden" in done and ">Completed</h2>" in done
    assert "last 14 days" in done
    assert 'class="task-row tv-row done"' in done
    assert "data-plan" not in done  # a done task has no do-date to give


def test_finished_workstreams_sit_on_a_line_under_the_table(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    shipped = projects_svc.create_workstream(db, project_id=project.id, name="Shipped")
    projects_svc.update_workstream(db, shipped.id, status=WorkstreamStatus.done)
    html = table(client, project.id)
    assert f'id="tt-ws-{shipped.id}"' not in html
    line = part(html, 'class="finished-workstreams tv-finished"')
    assert "Shipped" in line and f'hx-post="/ui/workstreams/{shipped.id}/toggle"' in line


def test_each_section_adds_into_itself(client, db) -> None:
    project = projects_svc.create_project(db, name="Calendar sync")
    api = projects_svc.create_workstream(db, project_id=project.id, name="API")
    html = table(client, project.id)
    api_part = part(html, f'id="tt-ws-{api.id}"')
    assert f'hx-target="#tt-rows-ws-{api.id}"' in api_part
    assert f'id="tt-rows-ws-{api.id}"' in api_part
    assert f'name="workstream_id" value="{api.id}"' in api_part
    none_part = part(html, 'id="tt-none"')
    assert 'hx-target="#tt-rows-none"' in none_part and 'name="workstream_id"' not in none_part

    # Added from the table (its part sends the view), the new task comes as its row.
    added = client.post(
        "/ui/tasks/quick-add",
        headers=TABLE,
        data={"title": "fetch", "project_id": str(project.id), "workstream_id": str(api.id)},
    ).text
    assert added.lstrip().startswith('<li class="task-row tv-row"') and "tv-cell" in added


def test_a_row_drawn_again_in_the_table_is_its_line(client, db) -> None:
    task = tasks_svc.create_task(db, title="parse", notes="- [ ] read\n- [ ] write")
    row = client.get(f"/ui/tasks/{task.id}/row", headers=TABLE).text
    assert row.lstrip().startswith(f'<li class="task-row tv-row" id="task-{task.id}"')
    assert row.count("<li") - row.count('<li class="subtask') == 1  # one row, its sub-tasks in it

    # Its box stepped on from review: done.
    tasks_svc.set_status(db, task.id, TaskStatus.needs_review)
    ticked = client.post(f"/ui/tasks/{task.id}/toggle", headers=TABLE).text
    assert 'class="task-row tv-row done"' in ticked

    # A sub-task ticked comes back with its sub-tasks still shown.
    sub = client.post(
        f"/ui/tasks/{task.id}/subtasks/0/toggle", headers=TABLE, data={"text": "read"}
    ).text
    assert 'aria-expanded="true"' in sub
    assert f'id="tv-subtasks-{task.id}">' in sub  # not hidden
    assert "1/2" in sub
