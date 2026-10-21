"""List and details, a view of a project's Tasks tab
(partials/project_tasks/pane.html): a section a workstream, a line a task
with its fields in slots, each line carrying its details for the pane, the
finished workstreams on a line and the finished work behind Show completed;
and a task's line drawn again in the view (X-Tasks-View: pane)."""

import re
from datetime import date, timedelta

import pytest

from app.models import TaskOwner, TaskPriority, TaskStatus
from app.services import projects as projects_svc
from app.services import tasks as tasks_svc

TODAY = date.today()
PANE = {"X-Tasks-View": "pane"}


@pytest.fixture
def made(db) -> dict:
    project = projects_svc.create_project(db, name="Calendar sync")
    api = projects_svc.create_workstream(db, project_id=project.id, name="API")
    shed = projects_svc.create_workstream(db, project_id=project.id, name="Shed")
    parse = tasks_svc.create_task(
        db,
        title="parse",
        project_id=project.id,
        workstream_id=api.id,
        planned_for=TODAY,
        due=TODAY + timedelta(days=2),
        priority=TaskPriority.high,
        estimate_minutes=90,
        notes="Context first.\n\n- [x] read\n- [ ] write\n- a bullet",
    )
    review = tasks_svc.create_task(
        db,
        title="review",
        project_id=project.id,
        workstream_id=api.id,
        owner=TaskOwner.claude,
        status=TaskStatus.needs_review,
    )
    tidy = tasks_svc.create_task(db, title="tidy", project_id=project.id)
    painted = tasks_svc.create_task(db, title="paint", project_id=project.id, workstream_id=shed.id)
    tasks_svc.set_status(db, painted.id, TaskStatus.done)
    db.flush()
    return {
        "project": project.id,
        "api": api.id,
        "shed": shed.id,
        "parse": parse.id,
        "review": review.id,
        "tidy": tidy.id,
        "paint": painted.id,
    }


def pane_page(client, made) -> str:
    return client.get(f"/projects/{made['project']}/tasks?view=pane").text


def line(page: str, task_id: int) -> str:
    """A task's line, from its <li> to its end."""
    start = page.index(f'id="task-{task_id}"')
    start = page.rindex("<li", 0, start)
    return page[start : page.index("</li>", page.index("</template>", start)) + len("</li>")]


def test_a_section_a_workstream_then_the_tasks_in_none(client, made) -> None:
    page = pane_page(client, made)
    assert 'class="task-lists tasks-in-pane"' in page
    api = page[page.index(f'data-fold-key="ws-{made["api"]}"') :]
    api = api[: api.index("</section>")]
    # Its head folds it, names it and says how far it is; its lines file into it.
    assert f'data-file-workstream="{made["api"]}"' in page
    assert "data-fold" in api and ">API</h2>" in api and ">0/2</span>" in api
    assert 'class="tv-meter" role="img" aria-label="0 of 2 done"' in api
    # Each section is a group for the cursor's keys (N, Shift+J/K).
    assert page.count("data-task-group") == 3
    assert f'id="task-{made["parse"]}"' in api and f'id="task-{made["review"]}"' in api
    # Its composer adds to its own list, in the workstream.
    assert f'hx-target="#lp-ws-{made["api"]}"' in api
    assert f'name="workstream_id" value="{made["api"]}"' in api
    loose = page[page.index('data-fold-key="loose"') :]
    loose = loose[: loose.index("</section>")]
    assert f'data-file-project="{made["project"]}"' in loose
    assert ">No workstream</h2>" in loose and '<span class="count">1</span>' in loose
    assert f'id="task-{made["tidy"]}"' in loose and 'hx-target="#lp-loose"' in loose


def test_with_no_workstreams_the_tasks_are_tasks(client, db) -> None:
    project = projects_svc.create_project(db, name="Garden")
    tasks_svc.create_task(db, title="dig", project_id=project.id)
    page = client.get(f"/projects/{project.id}/tasks?view=pane").text
    assert ">Tasks</h2>" in page and ">No workstream</h2>" not in page
    # Nothing done: Show completed only keeps its place, and the pane says how to pick.
    assert 'id="tasks-show-done" data-none' in page
    assert "Pick a task to see it here." in page


def test_a_line_is_its_box_title_and_fields_in_slots(client, made) -> None:
    parse = line(pane_page(client, made), made["parse"])
    assert 'tabindex="-1"' in parse and f'data-task-id="{made["parse"]}"' in parse
    assert 'data-task-title="parse"' in parse
    head = parse[: parse.index("<template")]
    assert 'class="task-check"' in head and 'class="task-title-btn"' in head
    assert "1/2" in head  # its sub-tasks done
    assert 'data-priority="high"' in head
    assert '<span class="tv-date">today</span>' in head
    # Its deadline with its word, and without it for where room is short.
    due = r'class="tv-due chip warn">due (\w{3} \d+ \w{3})</span><span class="tv-due chip warn">\1<'
    assert re.search(due, head)
    # Its quick do-dates, for the hover; Delete is the line's key alone (tasks.js).
    assert 'class="tv-quick"' in head and 'data-plan="tomorrow"' in head
    assert "task-delete" not in head
    review = line(pane_page(client, made), made["review"])
    assert 'class="chip tv-chip needs_review"' in review[: review.index("<template")]


def test_a_line_carries_its_details_for_the_pane(client, made) -> None:
    parse = line(pane_page(client, made), made["parse"])
    details = parse[parse.index('<template class="lp-source">') : parse.index("</template>")]
    assert "Mark done" in details and f'href="/tasks/{made["parse"]}"' in details
    assert "data-lp-edit" in details and ">parse</button></h2>" in details
    for field in ("Workstream", "Do-date", "Due", "Priority", "Estimate", "Owner"):
        assert f"<dt>{field}</dt>" in details
    assert "<dd>API</dd>" in details and "1h 30m" in details and ">High</span>" in details
    # Its quick do-dates, today's slot kept empty, and its description with
    # its sub-tasks ticked in place, each answering with the line.
    assert 'data-plan="tomorrow"' in details and 'data-plan="today"' not in details
    assert "Context first." in details and "a bullet" in details
    assert f'hx-post="/ui/tasks/{made["parse"]}/subtasks/1/toggle"' in details
    assert f'hx-target="#task-{made["parse"]}"' in details
    tidy = line(pane_page(client, made), made["tidy"])
    nones = ("No workstream", "No do-date", "No deadline", "No priority", "No estimate")
    for none in (*nones, "No description."):
        assert none in tidy


def test_finished_workstreams_on_a_line_finished_work_behind_show_completed(client, made) -> None:
    page = pane_page(client, made)
    finished = page[page.index('class="finished-workstreams lp-finished"') :]
    assert f'id="workstream-{made["shed"]}"' in finished[: finished.index("</section>")]
    assert "data-show-done" in page and "Show completed" in page
    done = page[page.index("data-done-part") :]
    done = done[: done.index("</section>")]
    assert "hidden" in done[: done.index(">")]
    assert f'id="task-{made["paint"]}"' in done and "last 14 days" in done
    # It folds too, and is a group for the cursor's keys.
    assert 'data-task-group data-fold-key="done"' in page and "data-fold " in done
    assert 'class="task-row lp-line done"' in done


def test_a_line_drawn_again_is_one_line_with_its_details(client, made) -> None:
    for got in (
        client.get(f"/ui/tasks/{made['parse']}/row", headers=PANE).text,
        client.post(
            f"/ui/tasks/{made['parse']}/subtasks/1/toggle", data={"text": "write"}, headers=PANE
        ).text,
    ):
        got = got.strip()
        assert got.startswith('<li class="task-row lp-line') and got.endswith("</li>")
        assert got.count('class="task-row') == 1 and f'id="task-{made["parse"]}"' in got
        assert '<template class="lp-source">' in got
    assert "2/2" in got  # the sub-task ticked, in its count and its details
    ticked = client.post(f"/ui/tasks/{made['tidy']}/toggle", headers=PANE).text
    assert 'class="task-row lp-line done"' in ticked and ">Done</span>" in ticked


def test_a_task_added_comes_back_as_a_line(client, made) -> None:
    got = client.post(
        "/ui/tasks/quick-add",
        headers=PANE,
        data={"title": "plan", "project_id": made["project"], "workstream_id": made["api"]},
    )
    assert got.text.strip().startswith('<li class="task-row lp-line')
    assert got.headers["HX-Trigger"] == "task:added"
