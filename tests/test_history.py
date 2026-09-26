from datetime import date, timedelta

from app.models import TaskStatus
from app.services import history
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()


def test_every_change_is_recorded_with_who_made_it(db) -> None:
    home = projects_svc.create_project(db, name="Home")
    task = tasks_svc.create_task(db, title="Mow", planned_for=TODAY)
    tasks_svc.update_task(db, task.id, title="Mow the lawn", project_id=home.id)
    db.info["actor"] = "claude"
    tasks_svc.set_status(db, task.id, TaskStatus.done)

    steps = history.changes(db, task.id)
    assert [(s["change"], s["actor"]) for s in steps] == [
        ("updated", "claude"),
        ("updated", "oscar"),
        ("created", "oscar"),
    ]
    assert steps[0]["fields"] == [{"field": "status", "from": "todo", "to": "done"}]
    # Project by name; dates as written.
    assert {f["field"]: (f["from"], f["to"]) for f in steps[1]["fields"]} == {
        "title": ("Mow", "Mow the lawn"),
        "project_id": (None, "Home"),
    }
    assert steps[2]["snapshot"]["planned_for"] == TODAY.isoformat()


def test_a_save_that_changes_nothing_is_not_a_step(db) -> None:
    task = tasks_svc.create_task(db, title="Mow")
    tasks_svc.update_task(db, task.id, title="Mow", planned_for=None)
    assert [s["change"] for s in history.changes(db, task.id)] == ["created"]


def test_history_outlives_the_task(db) -> None:
    task = tasks_svc.create_task(db, title="Mow", due=TODAY + timedelta(days=2))
    task_id = task.id
    tasks_svc.delete_task(db, task_id)

    steps = history.changes(db, task_id)
    assert [s["change"] for s in steps] == ["deleted", "created"]
    assert history.last_known(db, [task_id])[task_id]["title"] == "Mow"
