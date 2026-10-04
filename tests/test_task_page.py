"""A task's own page (/tasks/<id>): its sheet as a document, saved as it is
written, going back to the page it was opened from; and Calendar's sheet
opening it."""

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
        "href": "/calendar?view=sheet", "label": "Calendar"}
    assert back_link("/today") == {"href": "/today", "label": "Today"}
    assert back_link("/projects/3") == {"href": "/projects/3", "label": "Project"}
    assert back_link("/projects/3/gantt") == {"href": "/projects/3/gantt", "label": "Gantt"}
    assert back_link("/projects/3/tasks") == {"href": "/projects/3/tasks", "label": "Tasks"}
    assert back_link("/plan") == {"href": "/plan", "label": "Plan"}
    assert back_link(f"/day/{TODAY.isoformat()}", TODAY) == {
        "href": f"/day/{TODAY.isoformat()}", "label": "Today"}
    # Another site, another task's page, or nothing: Projects.
    for url in ("https://elsewhere.example/x", "//evil.example/calendar", "/tasks/4", ""):
        assert back_link(url)["href"] in ("/projects", "/calendar")
    assert back_link("//evil.example/x") == {"href": "/projects", "label": "Projects"}
    assert back_link("") == {"href": "/projects", "label": "Projects"}


def test_the_page_saves_what_it_holds(client, db) -> None:
    task = tasks_svc.create_task(db, title="Plan the trip")
    db.commit()
    answer = client.post(f"/ui/tasks/{task.id}/page", data={
        "title": "Plan the Japan trip", "status": "todo", "owner": "oscar",
        "notes": "- flights\n- rail pass", "planned_for": TODAY.isoformat(), "estimate": "90",
    })
    assert answer.status_code == 204
    db.expire_all()
    saved = db.get(Task, task.id)
    assert (saved.title, saved.notes, saved.planned_for, saved.estimate_minutes) == (
        "Plan the Japan trip", "- flights\n- rail pass", TODAY, 90)


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
