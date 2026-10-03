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
