import gc
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app import migrate
from app.config import REPO_ROOT
from app.db import Base, make_engine
from app.services import task_runs
from app.services import tasks as tasks_svc

MIGRATION = '''"""{name}"""
from alembic import op

revision = "{revision}"
down_revision = "{down}"
branch_labels = None
depends_on = None


def upgrade():
    {body}


def downgrade():
    pass
'''


def newer(tmp_path: Path, monkeypatch, body: str) -> str:  # noqa: ANN001
    """A newer version of the app: the migrations with one more after the
    head, whose upgrade is `body`. Its revision."""
    from alembic.script import ScriptDirectory

    root = tmp_path / f"version-{uuid.uuid4().hex[:6]}"
    shutil.copytree(
        REPO_ROOT / "migrations", root / "migrations", ignore=shutil.ignore_patterns("__pycache__")
    )
    [head] = ScriptDirectory.from_config(migrate._config(tmp_path / "app.db")).get_heads()
    revision = uuid.uuid4().hex[:12]
    (root / "migrations" / "versions" / f"{revision}_newer.py").write_text(
        MIGRATION.format(name=body, revision=revision, down=head, body=body), encoding="utf-8"
    )
    monkeypatch.setattr(migrate, "REPO_ROOT", root)
    return revision


def the_version_before(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(migrate, "REPO_ROOT", REPO_ROOT)


def seeded(path: Path) -> None:
    """A database at the code's head, with a task and an update on it."""
    migrate.upgrade(path)
    engine = make_engine(f"sqlite:///{path}")
    try:
        with Session(engine) as db:
            task = tasks_svc.create_task(db, title="Keep my updates")
            task_runs.add_update(db, task, "agent", "An update a migration must keep.")
            db.commit()
    finally:
        engine.dispose()


def rows(path: Path, table: str) -> int:
    with closing(sqlite3.connect(path)) as db:
        return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def table_names(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as db:
        return {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_a_first_start_creates_the_database_at_the_codes_schema(tmp_path) -> None:
    path = tmp_path / "data" / "personal-calendar.db"
    migrate.upgrade(path)

    engine = make_engine(f"sqlite:///{path}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert set(Base.metadata.tables) <= tables
    assert len(migrate.current_revisions(path)) == 1
    # Nothing was there to copy first.
    assert not migrate.copies(path).exists()


def test_a_start_on_a_current_database_changes_nothing(tmp_path) -> None:
    path = tmp_path / "app.db"
    migrate.upgrade(path)
    revisions, before = migrate.current_revisions(path), path.read_bytes()
    # A connection the upgrade left open would be closed now, and its write
    # ahead log checkpointed into the file: the upgrade must close its own.
    gc.collect()
    migrate.upgrade(path)
    assert migrate.current_revisions(path) == revisions
    assert path.read_bytes() == before


def test_a_database_from_a_newer_app_is_left_alone(tmp_path) -> None:
    path = tmp_path / "app.db"
    migrate.upgrade(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE alembic_version SET version_num = 'f00dfacecafe'")

    with pytest.raises(migrate.DatabaseTooNew, match="f00dfacecafe"):
        migrate.upgrade(path)
    assert migrate.current_revisions(path) == {"f00dfacecafe"}


def test_the_migrations_end_in_one_head(tmp_path) -> None:
    # Two pull requests that each add a migration onto the same one leave
    # two heads, and every start fails ("Multiple head revisions"), until a
    # merge revision (alembic merge) joins them.
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(migrate._config(tmp_path / "app.db"))
    assert len(script.get_heads()) == 1, script.get_heads()


@pytest.mark.parametrize("branch", ["d4b7e9a2c1f5", "f3b6d0a2c8e1"])
def test_a_database_on_either_side_of_a_merge_comes_up_to_head(tmp_path, branch) -> None:
    from alembic import command
    from alembic.script import ScriptDirectory

    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), branch)
    migrate.upgrade(path)
    # The head, whichever migration it is by now.
    heads = ScriptDirectory.from_config(migrate._config(path)).get_heads()
    assert migrate.current_revisions(path) == set(heads)


def test_a_migration_that_rebuilds_a_table_keeps_the_rows_that_refer_to_it(
    tmp_path, monkeypatch
) -> None:
    # Alembic changes a table on SQLite by copying it and dropping the
    # original. With foreign keys on, the drop deleted the table's rows
    # first, and on cascade every task's updates, pull requests and runs.
    path = tmp_path / "app.db"
    seeded(path)
    rebuild = 'with op.batch_alter_table("tasks", recreate="always"):\n        pass'
    newer(tmp_path, monkeypatch, rebuild)

    migrate.upgrade(path)

    assert rows(path, "tasks") == 1
    assert rows(path, "task_updates") == 1


def test_a_migration_that_fails_leaves_nothing_of_itself(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app.db"
    seeded(path)
    before = migrate.current_revisions(path)
    newer(
        tmp_path,
        monkeypatch,
        'op.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")\n'
        '    raise RuntimeError("it fails halfway")',
    )

    # Each start fails as the first did, never on what one before it left.
    for _ in range(2):
        with pytest.raises(RuntimeError, match="it fails halfway"):
            migrate.upgrade(path)
        assert "probe" not in table_names(path)
        assert migrate.current_revisions(path) == before
    # Nothing migrated: no copy kept of a database unchanged, and nothing to
    # go back on.
    assert not list(migrate.copies(path).glob("*.db"))
    assert not migrate.go_back(path)


def test_a_migration_that_leaves_rows_pointing_nowhere_is_undone(tmp_path, monkeypatch) -> None:
    # Foreign keys are off while migrating; the rows a migration left
    # pointing nowhere are looked for before it commits.
    path = tmp_path / "app.db"
    seeded(path)
    newer(tmp_path, monkeypatch, 'op.execute("DELETE FROM tasks")')

    with pytest.raises(RuntimeError, match="task_updates"):
        migrate.upgrade(path)
    assert rows(path, "tasks") == 1


def test_a_database_is_copied_before_it_is_migrated(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app.db"
    seeded(path)
    head = migrate.current_revisions(path)
    copies = migrate.copies(path)
    copies.mkdir()
    # Copies from earlier migrations: the newest are kept.
    older = [copies / f"app-2026-01-0{day}-000000-older.db" for day in range(1, 8)]
    for copy in older:
        copy.write_bytes(b"")
    newer(tmp_path, monkeypatch, "pass")

    migrate.upgrade(path)

    kept = sorted(copies.glob("*.db"))
    assert len(kept) == migrate.KEPT
    assert kept[: migrate.KEPT - 1] == older[-(migrate.KEPT - 1) :]
    assert migrate.current_revisions(kept[-1]) == head
    assert rows(kept[-1], "task_updates") == 1


def test_the_version_before_puts_back_a_migration_never_come_up_on(tmp_path, monkeypatch) -> None:
    # A restart on an update: the new version migrated, then did not come
    # up. The version restarted on instead finds a database it cannot read,
    # and puts it back as it was rather than refuse it, and the app with it.
    path = tmp_path / "app.db"
    seeded(path)
    head = migrate.current_revisions(path)
    newer(tmp_path, monkeypatch, 'op.execute("CREATE TABLE newer (id INTEGER PRIMARY KEY)")')
    migrate.upgrade(path)

    the_version_before(monkeypatch)
    migrate.upgrade(path)

    assert migrate.current_revisions(path) == head
    assert "newer" not in table_names(path)
    assert rows(path, "task_updates") == 1


def test_a_version_that_cannot_come_up_puts_back_what_it_migrated(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app.db"
    seeded(path)
    head = migrate.current_revisions(path)
    newer(tmp_path, monkeypatch, "pass")
    migrate.upgrade(path)

    assert migrate.go_back(path)
    assert migrate.current_revisions(path) == head
    # Once: what it put back is the version before's to migrate again.
    assert not migrate.go_back(path)


def test_a_migration_the_app_came_up_on_is_never_put_back(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app.db"
    seeded(path)
    revision = newer(tmp_path, monkeypatch, "pass")
    migrate.upgrade(path)
    migrate.confirm(path)

    assert not migrate.go_back(path)
    the_version_before(monkeypatch)
    with pytest.raises(migrate.DatabaseTooNew, match=revision):
        migrate.upgrade(path)
    assert migrate.current_revisions(path) == {revision}


def test_sub_tasks_written_without_a_box_take_one(tmp_path) -> None:
    # Before 2026-10-11 every "- " line was a sub-task; now only boxed ones
    # are, so a description written the old way keeps its sub-tasks.
    from alembic import command

    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "c7a3f9e2d418")
    old = "Why it matters\n- fetch\n  * nested\n- [x] parsed\n```\n- code\n```"
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "INSERT INTO tasks (title, notes, status, owner, created_at, status_changed_at,"
            " acceptance, outcome) VALUES ('t', ?, 'todo', 'oscar', '2026-10-01 00:00:00',"
            " '2026-10-01 00:00:00', '', '')",
            (old,),
        )
        db.commit()
    migrate.upgrade(path)
    with closing(sqlite3.connect(path)) as db:
        [(notes,)] = db.execute("SELECT notes FROM tasks").fetchall()
    assert notes == "Why it matters\n- [ ] fetch\n  * [ ] nested\n- [x] parsed\n```\n- code\n```"


def test_a_task_id_is_never_given_twice_once_upgraded(tmp_path) -> None:
    from alembic import command

    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "e5f1a9c3d7b2")  # the version before
    engine = make_engine(f"sqlite:///{path}")
    try:
        with Session(engine) as db:
            kept = tasks_svc.create_task(db, title="Kept")
            task_runs.add_update(db, kept, "agent", "An update the rebuild must keep.")
            gone = tasks_svc.create_task(db, title="Gone")  # the newest, deleted
            db.commit()
            kept_id, gone_id = kept.id, gone.id
            tasks_svc.delete_task(db, gone_id)
            db.commit()
        indexes = {i["name"] for i in inspect(engine).get_indexes("tasks")}
    finally:
        engine.dispose()

    migrate.upgrade(path)

    with closing(sqlite3.connect(path)) as db:
        [sql] = db.execute("SELECT sql FROM sqlite_master WHERE name = 'tasks'").fetchone()
    assert "AUTOINCREMENT" in sql
    assert (rows(path, "tasks"), rows(path, "task_updates")) == (1, 1)
    engine = make_engine(f"sqlite:///{path}")
    try:
        assert {i["name"] for i in inspect(engine).get_indexes("tasks")} == indexes
        with Session(engine) as db:
            assert tasks_svc.get_task(db, kept_id).title == "Kept"
            # Past the one deleted before the upgrade, and past itself once deleted.
            new = tasks_svc.create_task(db, title="New")
            db.commit()
            assert new.id == gone_id + 1
            tasks_svc.delete_task(db, new.id)
            db.commit()
            assert tasks_svc.create_task(db, title="Newer").id == new.id + 1
    finally:
        engine.dispose()


def test_habits_leave_the_notes_their_checks_kept(tmp_path) -> None:
    import json

    from alembic import command

    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "9380518192ab")  # the version before
    blocks = [
        {"kind": "text", "text": "Slow morning."},
        {"kind": "habit", "habit": 1, "done": True, "text": "5k"},
        {"kind": "habit", "habit": 2, "done": False, "text": ""},
    ]
    with closing(sqlite3.connect(path)) as db:
        db.executemany(
            "INSERT INTO habits (id, slug, days, created_at) VALUES (?, ?, '', '2026-10-01')",
            [(1, "run"), (2, "stretch")],
        )
        db.executemany(
            "INSERT INTO habit_checks (habit_id, day, done, note, updated_at)"
            " VALUES (?, '2026-10-02', ?, ?, '2026-10-02 08:00:00')",
            [(1, True, "5k"), (2, False, "")],
        )
        db.execute(
            "INSERT INTO notebook_pages (day, blocks, version, writer, writer_seq, updated_at)"
            " VALUES ('2026-10-02', ?, 3, '', 0, '2026-10-02 08:00:00')",
            (json.dumps(blocks),),
        )
        db.commit()
    migrate.upgrade(path)
    with closing(sqlite3.connect(path)) as db:
        [(kept, version)] = db.execute("SELECT blocks, version FROM notebook_pages").fetchall()
        checks = db.execute("SELECT habit_id, done, note FROM habit_checks").fetchall()
        [sql] = db.execute("SELECT sql FROM sqlite_master WHERE name = 'habits'").fetchone()
    # The page holds its words alone, and a window open on it is out of date.
    assert (json.loads(kept), version) == ([{"kind": "text", "text": "Slow morning."}], 4)
    # A check keeps its note; one not done with nothing said goes.
    assert checks == [(1, 1, "5k")]
    assert "AUTOINCREMENT" in sql


def test_stays_leave_the_notes_their_items_kept(tmp_path) -> None:
    import json

    from alembic import command

    path = tmp_path / "app.db"
    command.upgrade(migrate._config(path), "b7e3c1a95d42")  # the version before
    pages = {
        # Its prose after it, a blank row between them, starts the page now.
        "2026-10-02": [
            {"kind": "stay", "text": "a note\n- [x] place: Leiden\n- [ ] accommodation:"},
            {"kind": "text", "text": "\nSlow morning.\n- [ ] Pay rent", "links": {"2": 7},
             "folded": [2]},
        ],
        # A page that held its stay alone; a name written twice is one item.
        "2026-10-03": [{"kind": "stay", "text": "\n- [ ] Place: Delft\n- [x] place: x\n- [ ]"}],
    }
    with closing(sqlite3.connect(path)) as db:
        db.executemany(
            "INSERT INTO notebook_pages (day, blocks, version, writer, writer_seq, updated_at)"
            " VALUES (?, ?, 3, '', 0, '2026-10-02 08:00:00')",
            [(day, json.dumps(blocks)) for day, blocks in pages.items()],
        )
        db.commit()
    migrate.upgrade(path)
    with closing(sqlite3.connect(path)) as db:
        kept = db.execute("SELECT day, blocks, version FROM notebook_pages ORDER BY day").fetchall()
        items = db.execute(
            "SELECT day, position, name, value, done FROM stay_items ORDER BY day, position"
        ).fetchall()
    # The pages hold their words alone, and a window open on one is out of date.
    assert [(day, json.loads(blocks), version) for day, blocks, version in kept] == [
        ("2026-10-02", [
            {"kind": "text", "text": "Slow morning.\n- [ ] Pay rent", "links": {"1": 7},
             "folded": [1]},
        ], 4),
        ("2026-10-03", [], 4),
    ]
    assert items == [
        ("2026-10-02", 0, "place", "Leiden", 1),
        ("2026-10-02", 1, "accommodation", "", 0),
        ("2026-10-03", 0, "Place", "Delft", 0),
    ]
    # Taken back, the stays are the pages' again, first on each.
    command.downgrade(migrate._config(path), "b7e3c1a95d42")
    with closing(sqlite3.connect(path)) as db:
        back = db.execute("SELECT day, blocks FROM notebook_pages ORDER BY day").fetchall()
    assert [(day, json.loads(blocks)) for day, blocks in back] == [
        ("2026-10-02", [
            {"kind": "stay", "text": "\n- [x] place: Leiden\n- [ ] accommodation:"},
            {"kind": "text", "text": "Slow morning.\n- [ ] Pay rent", "links": {"1": 7},
             "folded": [1]},
        ]),
        ("2026-10-03", [{"kind": "stay", "text": "\n- [ ] Place: Delft"}]),
    ]
