import sqlite3

import pytest
from sqlalchemy import inspect

from app import migrate
from app.db import Base, make_engine


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


def test_a_start_on_a_current_database_changes_nothing(tmp_path) -> None:
    path = tmp_path / "app.db"
    migrate.upgrade(path)
    revisions, before = migrate.current_revisions(path), path.read_bytes()
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
