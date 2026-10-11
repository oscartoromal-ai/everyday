"""The daily scan for what to improve (improve/), and the app's job running it."""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base, make_engine
from app.jobs import improve as improve_job
from app.models import Project, ProjectRepo, RouteUse, TaskOwner, TaskPriority
from app.services import tasks as tasks_svc
from improve import sources
from improve.findings import Finding
from improve.ledger import Ledger
from improve.scan import scan

# Two errors as the installed app logs them (its frames relative), the first
# twice, and lines that are not errors around them.
LOG = """\
2026-10-03 23:40:18,600 INFO uvicorn.access: 127.0.0.1:1 - "GET /today HTTP/1.1" 200
2026-10-03 23:40:18,679 ERROR uvicorn.error: Exception in ASGI application
Traceback (most recent call last):
  File "uvicorn\\protocols\\http\\httptools_impl.py", line 422, in run_asgi
  File "app\\desktop\\__init__.py", line 239, in open_window
  File "app\\desktop\\__init__.py", line 82, in hwnd
AttributeError: 'NoneType' object has no attribute 'Handle'
2026-10-04 09:00:00,000 WARNING apscheduler.executors.default: Run time of job was missed
2026-10-04 16:06:15,047 CRITICAL app.serve: Uncaught error in Thread-67 (_call)
Traceback (most recent call last):
  File "threading.py", line 1044, in _bootstrap_inner
  File "webview\\window.py", line 503, in evaluate_js
webview.errors.JavascriptException: {'name': 'TypeError'}
2026-10-04 17:00:00,000 ERROR uvicorn.error: Exception in ASGI application
Traceback (most recent call last):
  File "app\\desktop\\__init__.py", line 82, in hwnd
AttributeError: 'NoneType' object has no attribute 'Handle'
2026-10-04 18:00:00,000 ERROR app.services.github: Sync failed for account 12
"""


@pytest.fixture
def logs(tmp_path) -> Path:
    folder = tmp_path / "logs"
    folder.mkdir()
    (folder / "personal-calendar.log").write_text(LOG, encoding="utf-8")
    return folder


@pytest.fixture
def live_db(tmp_path):  # noqa: ANN201
    """A live app's database, as a file the scan opens read-only, and a session on it."""
    path = tmp_path / "live.db"
    engine = make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield path, session
    session.close()
    engine.dispose()


def test_errors_logged_are_grouped_by_where_they_came_from(logs) -> None:
    found = {f.title: f for f in sources.log_errors(logs, datetime(2026, 10, 1))}

    assert set(found) == {
        "AttributeError in app/desktop/__init__.py:hwnd",
        "JavascriptException in webview/window.py:evaluate_js",
        "app.services.github: Sync failed for account 12",
    }
    handle = found["AttributeError in app/desktop/__init__.py:hwnd"]
    assert handle.kind == "error" and handle.occurrences == 2
    assert "Logged 2 time(s)" in handle.evidence and "'Handle'" in handle.evidence


def test_errors_are_read_from_when_the_last_scan_read_to(logs) -> None:
    found = sources.log_errors(logs, datetime(2026, 10, 4, 12))

    assert sorted(f.occurrences for f in found) == [1, 1, 1]


def test_an_errors_numbers_do_not_make_it_another(logs) -> None:
    log = logs / "personal-calendar.log"
    log.write_text(
        LOG + "2026-10-04 19:00:00,000 ERROR app.services.github: Sync failed for account 7\n",
        encoding="utf-8",
    )
    github = [f for f in sources.log_errors(logs, datetime(2026, 10, 1)) if "github" in f.key]

    assert len(github) == 1 and github[0].occurrences == 2


def test_rotated_logs_are_read_oldest_first(logs) -> None:
    (logs / "personal-calendar.log.2").write_text("", encoding="utf-8")
    (logs / "personal-calendar.log.1").write_text("", encoding="utf-8")

    assert [p.name for p in sources.log_files(logs)] == [
        "personal-calendar.log.2",
        "personal-calendar.log.1",
        "personal-calendar.log",
    ]


def test_routes_failing_or_slow_are_findings(live_db) -> None:
    path, db = live_db
    today = date.today()
    db.add_all(
        [
            RouteUse(
                day=today, route="GET /today", requests=40, failures=0, total_ms=800, slowest_ms=90
            ),
            RouteUse(
                day=today,
                route="GET /gantt",
                requests=6,
                failures=0,
                total_ms=4800,
                slowest_ms=1500,
            ),
            RouteUse(
                day=today,
                route="POST /ui/tasks",
                requests=3,
                failures=2,
                total_ms=30,
                slowest_ms=12,
            ),
            RouteUse(
                day=today - timedelta(days=30),
                route="GET /old",
                requests=9,
                failures=9,
                total_ms=9,
                slowest_ms=1,
            ),
        ]
    )
    db.commit()

    stats = sources.route_stats(path, today - timedelta(days=7))
    assert [s.route for s in stats] == ["GET /today", "GET /gantt", "POST /ui/tasks"]
    found = {(f.kind, f.key) for f in sources.route_use(stats, today)}
    assert found == {("slow-route", "GET /gantt"), ("failing-route", "POST /ui/tasks")}


def test_a_database_from_before_use_was_counted_has_none(tmp_path) -> None:
    path = tmp_path / "old.db"
    make_engine(f"sqlite:///{path}").connect().close()

    assert sources.route_stats(path, date.today()) == []


PYTEST_OUTPUT = """\
..F..F
=================================== FAILURES ===================================
___________________________ test_saves_a_task[draft] ___________________________
tests/test_api.py:10: in test_saves_a_task
    assert response.status_code == 200
E   assert 500 == 200
______________________________ TestSheet.test_drag ______________________________
tests/test_sheet.py:20: in test_drag
E   TimeoutError
============================= slowest 25 durations =============================
41.20s call     tests/test_sheet.py::TestSheet::test_drag
3.00s setup    tests/test_api.py::test_saves_a_task[draft]
=========================== short test summary info ============================
FAILED tests/test_api.py::test_saves_a_task[draft] - assert 500 == 200
FAILED tests/test_sheet.py::TestSheet::test_drag - TimeoutError
2 failed, 4 passed in 700.50s (0:11:40)
"""


def test_pytest_output_is_read() -> None:
    run = sources.parse_pytest(1, PYTEST_OUTPUT)

    assert run.failed == [
        "tests/test_api.py::test_saves_a_task[draft]",
        "tests/test_sheet.py::TestSheet::test_drag",
    ]
    assert run.seconds == 700.5
    assert run.durations[0] == (41.2, "call tests/test_sheet.py::TestSheet::test_drag")
    assert "assert 500 == 200" in run.section("tests/test_api.py::test_saves_a_task[draft]")
    assert "TimeoutError" in run.section("tests/test_sheet.py::TestSheet::test_drag")


def test_a_test_failing_again_fails_one_passing_again_is_flaky(monkeypatch) -> None:
    again = (
        "F.\nFAILED tests/test_api.py::test_saves_a_task[draft] - assert\n"
        "1 failed, 1 passed in 2s\n"
    )
    runs = iter([sources.parse_pytest(1, PYTEST_OUTPUT), sources.parse_pytest(1, again)])
    monkeypatch.setattr(sources, "run_pytest", lambda checkout, *args: next(runs))

    found = {f.key: f for f in sources.tests(Path("."))}

    assert found["tests/test_api.py::test_saves_a_task[draft]"].kind == "failing-test"
    assert found["tests/test_sheet.py::TestSheet::test_drag"].kind == "flaky-test"
    slow = found["suite"]
    assert slow.kind == "slow-tests" and slow.title == "The tests take 12 minutes"


def test_a_suite_that_does_not_run_is_a_failing_test(monkeypatch) -> None:
    broken = sources.parse_pytest(4, "ERROR: file or directory not found\n")
    monkeypatch.setattr(sources, "run_pytest", lambda checkout, *args: broken)

    [found] = sources.tests(Path("."))

    assert (found.kind, found.title) == ("failing-test", "The test suite does not run")


def test_tasks_given_to_claude_on_the_apps_project_most_pressing_first(
    live_db, monkeypatch
) -> None:
    path, db = live_db
    app_project, other = Project(name="personal-life-app"), Project(name="Pylon")
    db.add_all([app_project, other])
    db.flush()
    db.add(
        ProjectRepo(
            project_id=app_project.id, location="https://github.com/oscartoromal-ai/everyday-app"
        )
    )
    claude = TaskOwner.claude
    tasks_svc.create_task(db, title="Tidy the rail", owner=claude, project_id=app_project.id)
    tasks_svc.create_task(
        db,
        title="Fix the sheet",
        owner=claude,
        project_id=app_project.id,
        priority=TaskPriority.high,
        notes="- Drag across days",
    )
    tasks_svc.create_task(db, title="Oscar's own", project_id=app_project.id)
    tasks_svc.create_task(db, title="Elsewhere", owner=claude, project_id=other.id)
    db.commit()
    monkeypatch.setattr(sources, "repo_slug", lambda checkout: "oscartoromal-ai/everyday-app")

    found = sources.tasks(path, Path("."), "")

    assert [f.title for f in found] == ["Fix the sheet", "Tidy the rail"]
    assert "priority high" in found[0].evidence and "Drag across days" in found[0].evidence


def test_with_no_project_listing_the_repo_the_one_named_is_taken(live_db, monkeypatch) -> None:
    path, db = live_db
    db.add(Project(name="personal-life-app"))
    db.commit()
    monkeypatch.setattr(sources, "repo_slug", lambda checkout: "oscartoromal-ai/everyday-app")

    assert sources.tasks(path, Path("."), "personal-life-app") == []
    with pytest.raises(sources.SourceFailed):
        sources.tasks(path, Path("."), "")


def _finding(kind: str, key: str, occurrences: int = 1) -> Finding:
    return Finding(kind, key, f"{kind} {key}", f"shows {key}", occurrences)


def test_the_ledger_tells_new_findings_from_known_ones(tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger.json")
    monday = date(2026, 10, 5)
    lint = _finding("lint", "E501")

    assert [e.fingerprint for e in ledger.meet([lint], monday)] == [lint.fingerprint]
    assert ledger.meet([lint], monday + timedelta(days=1)) == []
    entry = ledger.entries[lint.fingerprint]
    assert (entry.scans, entry.first_seen, entry.last_seen) == (2, "2026-10-05", "2026-10-06")


def test_the_pick_takes_the_most_pressing_open_one(tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger.json")
    today = date(2026, 10, 20)
    ledger.meet([_finding("error", "old")], today - timedelta(days=15))
    ledger.meet(
        [
            _finding("lint", "E501", 9),
            _finding("error", "rare", 1),
            _finding("error", "often", 5),
            _finding("failing-test", "picked"),
        ],
        today,
    )
    ledger.mark(_finding("failing-test", "picked").fingerprint, "picked", today)

    picks = [e.key for e in ledger.candidates(today)]

    # Not the one being fixed, nor the error not met for weeks.
    assert picks == ["often", "rare", "E501"]


def test_a_finding_met_after_its_fix_opens_again(tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger.json")
    error = _finding("error", "x")
    ledger.meet([error], date(2026, 10, 5))
    ledger.mark(error.fingerprint, "done", date(2026, 10, 6), pr="https://github.com/o/r/pull/1")

    assert ledger.meet([error], date(2026, 10, 9))
    entry = ledger.entries[error.fingerprint]
    assert (entry.status, entry.reopened, entry.pr) == ("open", 1, "https://github.com/o/r/pull/1")


def test_the_ledger_is_kept_across_scans(tmp_path) -> None:
    ledger = Ledger(tmp_path / "ledger.json", last_scan=datetime(2026, 10, 5, 2, 30))
    ledger.meet([_finding("lint", "E501")], date(2026, 10, 5))
    ledger.save()

    again = Ledger.load(tmp_path / "ledger.json")
    assert again.last_scan == datetime(2026, 10, 5, 2, 30)
    assert again.entries == ledger.entries
    with pytest.raises(ValueError):
        again.mark(next(iter(again.entries)), "maybe", date.today())


def test_a_scan_writes_its_report_ledger_and_brief(tmp_path, logs, live_db) -> None:
    path, db = live_db
    today = date(2026, 10, 5)
    db.add(
        RouteUse(
            day=today, route="GET /today", requests=12, failures=0, total_ms=600, slowest_ms=80
        )
    )
    db.commit()
    out = tmp_path / "improve"

    report = scan(
        checkout=Path("."),
        db=path,
        logs=logs,
        out=out,
        only=("log", "usage"),
        now=datetime(2026, 10, 5, 2, 30),
    )

    assert report.pick.title == "AttributeError in app/desktop/__init__.py:hwnd"
    brief = (out / "brief.md").read_text(encoding="utf-8")
    assert brief.startswith("# AttributeError in app/desktop/__init__.py:hwnd")
    assert f"Improves: {report.pick.fingerprint}" in brief
    assert str(logs / "personal-calendar.log") in brief
    text = (out / "reports" / "2026-10-05.md").read_text(encoding="utf-8")
    assert "| error | AttributeError in app/desktop/__init__.py:hwnd | 2 | new |" in text
    assert "| `GET /today` | 12 | 0 | 50 | 80 |" in text
    data = json.loads((out / "reports" / "2026-10-05.json").read_text(encoding="utf-8"))
    assert data["pick"] == report.pick.fingerprint and data["sources"]["log"]["found"] == 3

    # The next day's scan reads the log on from there: nothing new in it.
    again = scan(
        checkout=Path("."),
        db=path,
        logs=logs,
        out=out,
        only=("log",),
        now=datetime(2026, 10, 6, 2, 30),
    )
    assert again.findings == []
    # Yesterday's errors wait to be picked all the same.
    assert again.pick.fingerprint == report.pick.fingerprint


def test_a_source_that_cannot_run_leaves_the_others(tmp_path, logs) -> None:
    report = scan(
        checkout=Path("."),
        db=tmp_path / "none.db",
        logs=logs,
        out=tmp_path / "out",
        only=("log", "usage"),
        now=datetime(2026, 10, 5, 2, 30),
    )

    assert report.sources["usage"].problem.startswith("no database")
    assert report.sources["log"].found == 3


def test_the_scan_is_due_once_a_day_after_its_time() -> None:
    after = "02:30"
    assert not improve_job.due(datetime(2026, 10, 5, 2, 0), date(2026, 10, 4), after)
    assert improve_job.due(datetime(2026, 10, 5, 2, 30), date(2026, 10, 4), after)
    # The machine asleep at 02:30: as soon as it is awake.
    assert improve_job.due(datetime(2026, 10, 5, 9, 15), None, after)
    assert not improve_job.due(datetime(2026, 10, 5, 9, 15), date(2026, 10, 5), after)


def test_the_app_runs_masters_scan_in_its_own_checkout(tmp_path, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings().storage, "db_path", str(tmp_path / "data" / "app.db"))
    monkeypatch.setattr(improve_job, "repo", lambda: tmp_path / "repo")
    monkeypatch.setattr(improve_job.shutil, "which", lambda name: name)
    ran: list[tuple[list[str], Path | None]] = []

    def run(cmd, **kwargs) -> subprocess.CompletedProcess:  # noqa: ANN001, ANN003
        ran.append((cmd, kwargs.get("cwd")))
        assert not [k for k in kwargs["env"] if k.startswith("PC_")]
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(improve_job.subprocess, "run", run)
    monkeypatch.setenv("PC_HOME", str(tmp_path / "home"))

    assert improve_job.run(datetime(2026, 10, 5, 3, 0))
    folder = tmp_path / "data" / "improve"
    checkout = folder / "checkout"
    assert [cmd[3:] for cmd, _ in ran[:3]] == [
        ["fetch", "--quiet", "origin", "master"],
        ["worktree", "prune"],
        ["worktree", "add", "--detach", "--force", str(checkout), "origin/master"],
    ]
    # The picks being fixed followed, the scan, then the next pick launched.
    steps = [(cmd[5:7], cwd) for cmd, cwd in ran[3:]]
    assert steps == [
        (["improve.run", "follow"], checkout),
        (["improve.scan", "--home"], checkout),
        (["improve.run", "launch"], checkout),
    ]
    scan_cmd = ran[4][0]
    assert scan_cmd[1:6] == ["run", "--quiet", "python", "-m", "improve.scan"]
    assert scan_cmd[scan_cmd.index("--out") + 1] == str(folder)
    launch_cmd = ran[5][0]
    assert launch_cmd[launch_cmd.index("--repo") + 1] == str(tmp_path / "repo")
    assert launch_cmd[launch_cmd.index("--runner") + 1] == "t3"
    assert (folder / "last-run.txt").read_text(encoding="utf-8") == "2026-10-05"

    # Once a day.
    assert not improve_job.run(datetime(2026, 10, 5, 9, 0))


def test_between_days_the_picks_are_followed_from_the_checkout(tmp_path, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings().storage, "db_path", str(tmp_path / "data" / "app.db"))
    monkeypatch.setattr(improve_job, "repo", lambda: tmp_path / "repo")
    ran: list[list[str]] = []
    monkeypatch.setattr(
        improve_job.subprocess, "run",
        lambda cmd, **kwargs: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )

    # Not before the first day's scan has made the checkout.
    assert not improve_job.follow()
    (tmp_path / "data" / "improve" / "checkout" / ".git").mkdir(parents=True)
    assert improve_job.follow()
    assert [cmd[5:7] for cmd in ran] == [["improve.run", "follow"]]
    # Nor while the day's run holds the lock.
    with improve_job._lock:
        assert not improve_job.follow()


def test_turned_off_the_scan_never_runs(monkeypatch) -> None:
    from app.config import get_settings
    from app.jobs.scheduler import create_scheduler

    jobs = {"improvement_scan", "improvement_follow"}
    assert jobs <= {j.id for j in create_scheduler().get_jobs()}
    monkeypatch.setattr(get_settings().improve, "enabled", False)
    assert not jobs & {j.id for j in create_scheduler().get_jobs()}
    assert not improve_job.run(datetime(2026, 10, 5, 3, 0))


def test_the_repo_is_the_one_configured(tmp_path, monkeypatch) -> None:
    # A version GitHub built knows no checkout on this machine: config names it.
    from app.config import get_settings

    (tmp_path / "repo" / ".git").mkdir(parents=True)
    monkeypatch.setattr(improve_job, "FROZEN", True)
    monkeypatch.setattr("app.desktop.update.build_info", lambda: {"repo": None})
    assert improve_job.repo() is None
    monkeypatch.setattr(get_settings().improve, "repo", str(tmp_path / "repo"))
    assert improve_job.repo() == tmp_path / "repo"
    monkeypatch.setattr(get_settings().improve, "repo", str(tmp_path / "gone"))
    assert improve_job.repo() is None


def _tool_writes(monkeypatch, stdout: str) -> None:  # noqa: ANN001
    def run_tool(cmd, cwd, timeout) -> subprocess.CompletedProcess:  # noqa: ANN001
        return subprocess.CompletedProcess(cmd, 1, stdout, "")

    monkeypatch.setattr(sources, "run_tool", run_tool)


def test_vulnerable_packages_are_findings(tmp_path, monkeypatch) -> None:
    (tmp_path / ".venv" / "Lib" / "site-packages").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "python3.13" / "site-packages").mkdir(parents=True)
    audit = {
        "dependencies": [
            {
                "name": "pyjwt",
                "version": "2.13.0",
                "vulns": [
                    {"id": "PYSEC-1", "fix_versions": ["2.14.0"], "description": "Forged tokens."},
                    {"id": "PYSEC-2", "fix_versions": [], "description": ""},
                ],
            },
            {"name": "fastapi", "version": "1.0.0", "vulns": []},
        ]
    }
    _tool_writes(monkeypatch, json.dumps(audit))

    [found] = sources.vulnerable_dependencies(tmp_path)

    assert (found.key, found.title) == ("pyjwt|2.13.0", "pyjwt 2.13.0 has 2 known vulnerabilities")
    assert "PYSEC-1: fixed in 2.14.0. Forged tokens." in found.evidence
    assert "PYSEC-2: fixed in no release yet." in found.evidence


def test_outdated_packages_pyproject_names_are_one_finding(tmp_path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi[standard]>=0.115", "SQLAlchemy>=2.0"]\n'
        '[dependency-groups]\ndev = ["pytest>=8.0"]\n',
        encoding="utf-8",
    )
    listed = [
        {"name": "fastapi", "version": "1.0", "latest_version": "1.1"},
        {"name": "sqlalchemy", "version": "2.0", "latest_version": "2.1"},
        {"name": "anyio", "version": "4.0", "latest_version": "4.1"},
    ]
    _tool_writes(monkeypatch, json.dumps(listed))

    [found] = sources.outdated_dependencies(tmp_path)

    assert found.title == "2 dependencies have newer releases"
    assert found.evidence == "- fastapi 1.0 to 1.1\n- sqlalchemy 2.0 to 2.1"


def test_lint_is_a_finding_for_each_rule_broken(tmp_path, monkeypatch) -> None:
    def problem(code: str, file: str, row: int) -> dict:
        return {
            "code": code,
            "message": f"{code} broken",
            "filename": str(tmp_path / file),
            "location": {"row": row},
        }

    problems = [
        problem("E501", "app/a.py", 3),
        problem("E501", "app/b.py", 9),
        problem("F401", "app/a.py", 1),
    ]
    _tool_writes(monkeypatch, json.dumps(problems))

    found = {f.key: f for f in sources.lint(tmp_path)}

    assert found["E501"].title == "ruff E501: E501 broken (2 place(s))"
    assert found["E501"].evidence == "- app/a.py:3: E501 broken\n- app/b.py:9: E501 broken"
    assert found["F401"].occurrences == 1
