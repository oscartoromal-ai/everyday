import os

# TestClient addresses the app as "testserver"; allow it through the browser
# guard before the cached Settings is first built.
os.environ.setdefault("PC_SERVER__EXTRA_HOSTS", '["testserver"]')

from collections.abc import Generator  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app import models  # noqa: F401, E402  (registers models on Base.metadata)
from app.db import Base, make_engine  # noqa: E402


@pytest.fixture
def db(tmp_path) -> Generator[Session, None, None]:
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def app_db(tmp_path, monkeypatch) -> Generator[sessionmaker[Session], None, None]:
    """Point the process-global engine/session factory (used by MCP tools and
    background jobs) at a throwaway database."""
    import app.db as db_mod

    engine = make_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "_session_factory", factory)
    yield factory
    engine.dispose()
