"""A task's own page (/tasks/<id>): its sheet as a document, saved as it is
written, going back to the page it was opened from; and Calendar's sheet
opening it."""

import re
from datetime import date

from app.models import Task
from app.services import tasks as tasks_svc
from app.ui.views import back_link

TODAY = date.today()


def test_the_page_shows_the_task_and_goes_back_where_it_was_opened(client, db) -> None:
    task = tasks_svc.create_task(db, title="Plan the trip", notes="- flights\nWhy: holidays")
    db.commit()
    html = client.get(
        f"/tasks/{task.id}", headers={"referer": "http://127.0.0.1:8377/calendar?view=sheet"}
    ).text
    assert 'data-sheet="page"' in html
    assert "<title>Plan the trip · Personal Calendar</title>" in html
    assert '<a class="page-back" href="/calendar?view=sheet">Calendar</a>' in html
    assert "- flights\nWhy: holidays</textarea>" in html


def test_a_missing_task_is_not_found(client) -> None:
    assert client.get("/tasks/999").status_code == 404


def test_back_is_one_of_the_apps_pages_named_else_projects() -> None:
    assert back_link("http://host/calendar?view=sheet") == {
        "href": "/calendar?view=sheet",
        "label": "Calendar",
    }
    assert back_link("/today") == {"href": "/today", "label": "Today"}
    assert back_link("/projects/3") == {"href": "/projects/3", "label": "Project"}
    assert back_link("/projects/3/gantt") == {"href": "/projects/3/gantt", "label": "Gantt"}
    assert back_link("/projects/3/tasks") == {"href": "/projects/3/tasks", "label": "Tasks"}
    assert back_link("/plan") == {"href": "/plan", "label": "Plan"}
    assert back_link(f"/day/{TODAY.isoformat()}", TODAY) == {
        "href": f"/day/{TODAY.isoformat()}",
        "label": "Today",
    }
    # Every page the command menu can open a task from: the sidebar's, by its
    # names (a day or month of one too), a project's documents, and Settings'.
    assert back_link("/garmin/2026-10-01") == {"href": "/garmin/2026-10-01", "label": "Garmin"}
    assert back_link("/spending") == {"href": "/spending", "label": "Spending"}
    assert back_link("/repositories") == {"href": "/repositories", "label": "Repositories"}
    assert back_link("/projects/3/docs/7") == {"href": "/projects/3/docs/7", "label": "Document"}
    assert back_link("/models") == {"href": "/models", "label": "Models"}
    assert back_link("/projects/x") == {"href": "/projects", "label": "Projects"}
    # Another site, another task's page, or nothing: Projects.
    for url in ("https://elsewhere.example/x", "//evil.example/calendar", "/tasks/4", ""):
        assert back_link(url)["href"] in ("/projects", "/calendar")
    assert back_link("//evil.example/x") == {"href": "/projects", "label": "Projects"}
    assert back_link("") == {"href": "/projects", "label": "Projects"}


def test_the_page_saves_what_it_holds(client, db) -> None:
    task = tasks_svc.create_task(db, title="Plan the trip")
    db.commit()
    answer = client.post(
        f"/ui/tasks/{task.id}/page",
        data={
            "title": "Plan the Japan trip",
            "status": "todo",
            "owner": "oscar",
            "notes": "- flights\n- rail pass",
            "planned_for": TODAY.isoformat(),
            "estimate": "90",
        },
    )
    assert answer.status_code == 204
    db.expire_all()
    saved = db.get(Task, task.id)
    assert (saved.title, saved.notes, saved.planned_for, saved.estimate_minutes) == (
        "Plan the Japan trip",
        "- flights\n- rail pass",
        TODAY,
        90,
    )


def test_deleted_from_its_page_it_goes_back(client, db) -> None:
    task = tasks_svc.create_task(db, title="Plan the trip")
    db.commit()
    answer = client.post(f"/ui/tasks/{task.id}/delete", data={"back": "/calendar?view=sheet"})
    assert answer.headers["HX-Redirect"] == "/calendar?view=sheet"
    assert db.get(Task, task.id) is None


def test_a_task_written_on_calendars_sheet_is_named_for_its_page(client, db) -> None:
    answer = client.post(
        f"/ui/day-sheet?start={TODAY.isoformat()}",
        json={"ops": [{"op": "task", "day": TODAY.isoformat(), "title": "Plan the trip"}]},
    )
    task = db.query(Task).filter_by(title="Plan the trip").one()
    assert answer.headers["X-Task-Created"] == str(task.id)
    # Its title on the sheet opens its page.
    assert f'<a class="ds-title" href="/tasks/{task.id}"' in answer.text


def test_the_page_maps_its_project_its_workstreams_and_where_the_task_stands(client, db) -> None:
    from app.models import TaskOwner, TaskStatus
    from app.services import projects as projects_svc

    project = projects_svc.create_project(db, name="Everyday")
    lane = projects_svc.create_workstream(db, project_id=project.id, name="Usability")
    other = projects_svc.create_workstream(db, project_id=project.id, name="Phone")
    here = tasks_svc.create_task(
        db, title="Widen the task page", project_id=project.id, workstream_id=lane.id
    )
    tasks_svc.create_task(
        db,
        title="Agent's one",
        project_id=project.id,
        workstream_id=lane.id,
        owner=TaskOwner.claude,
    )
    finished = tasks_svc.create_task(
        db, title="Shipped", project_id=project.id, workstream_id=lane.id
    )
    tasks_svc.set_status(db, finished.id, TaskStatus.done)
    tasks_svc.create_task(db, title="Swipe", project_id=project.id, workstream_id=other.id)
    db.commit()
    html = client.get(f"/tasks/{here.id}").text
    assert f'<a class="map-project" href="/projects/{project.id}"' in html
    assert ">AGENTS.md<" in html
    # Its workstream open, the task marked; the other folded.
    assert f'aria-controls="map-lane-{lane.id}"' in html
    assert f'id="map-lane-{lane.id}">' in html
    assert f'id="map-lane-{other.id}" hidden>' in html
    # The task itself, and under it its description, the document open.
    assert f'class="map-row map-task is-here" href="/tasks/{here.id}" style="--depth: 1"' in html
    assert f'href="/tasks/{here.id}" style="--depth: 2" aria-current="page"' in html
    assert 'aria-label="Claude\'s"' in html
    assert "1 done" in html


def test_a_task_in_no_project_has_a_map_of_itself(client, db) -> None:
    task = tasks_svc.create_task(db, title="Loose end")
    db.commit()
    html = client.get(f"/tasks/{task.id}").text
    assert "No project" in html
    assert f'class="map-row map-task is-here" href="/tasks/{task.id}" style="--depth: 0"' in html
    assert f'href="/tasks/{task.id}" style="--depth: 1" aria-current="page"' in html


def test_its_agent_work_is_a_pane_shown_as_it_is_claudes(client, db) -> None:
    from app.models import TaskOwner

    mine = tasks_svc.create_task(db, title="Mine")
    theirs = tasks_svc.create_task(db, title="Theirs", owner=TaskOwner.claude)
    db.commit()
    html = client.get(f"/tasks/{mine.id}").text
    # The sidebar has the page's panes, and the strip of their icons.
    assert 'class="side" id="side" aria-label="Sidebar" data-tabbed' in html
    for pane in ("work", "outline", "history"):
        assert f'data-side-tab="{pane}"' in html and f'data-side-pane="{pane}"' in html
    assert re.search(r'data-side-pane="work"[^>]*data-owner="oscar"', html)
    assert "Hand to an agent" in html
    html = client.get(f"/tasks/{theirs.id}").text
    assert 'data-owner="claude"' in html
    assert 'id="task-run"' in html


def test_other_pages_keep_the_agent_window_alone(client) -> None:
    html = client.get("/today").text
    assert "data-tabbed" not in html
    assert 'id="agent-panel"' in html
