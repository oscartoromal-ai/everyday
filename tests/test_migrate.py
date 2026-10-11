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
