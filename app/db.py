"""Database engine and session management.

SQLite in WAL mode, one file, one engine per process. All datetimes are stored
as naive local wall time (see the v1 plan: single-machine wall-time domain).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def make_engine(db_url: str | None = None) -> Engine:
    if db_url is None:
        settings = get_settings()
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{settings.db_path}"
    engine = create_engine(db_url)
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# scope="function": commit before the response goes out. FastAPI's default
# ("request") runs this teardown after sending, so a client that re-renders
# the moment a save returns (a drag, then a list refresh) could read the
# state from before the save.
DbSession = Annotated[Session, Depends(get_db, scope="function")]


@contextmanager
def session_scope(actor: str = "system") -> Generator[Session, None, None]:
    """Commit-on-success session for MCP tools ("claude") and background jobs
    ("system"). The actor is who the task history names for its changes;
    request sessions (get_db) are Oscar's."""
    session = get_session_factory()()
    session.info["actor"] = actor
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
