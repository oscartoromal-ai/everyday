import os

# TestClient addresses the app as "testserver"; allow it through the browser
# guard before the cached Settings is first built.
os.environ.setdefault("PC_SERVER__EXTRA_HOSTS", '["testserver"]')

import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections.abc import Generator  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app import models  # noqa: F401, E402  (registers models on Base.metadata)
from app.db import Base, make_engine  # noqa: E402


@pytest.fixture(autouse=True)
def keys_file(tmp_path, monkeypatch):
    """The keys chosen (app/services/keys.py) in a keys.toml of the test's
    own, never the one in the home the tests run from."""
    from app.services import keys as keys_svc

    path = tmp_path / "keys.toml"
    monkeypatch.setattr(keys_svc, "keys_file", lambda: path)
    return path


@pytest.fixture(autouse=True)
def everyday_files(tmp_path, monkeypatch):  # noqa: ANN201
    """The everyday files (projects' context, as files) in a throwaway folder,
    never the machine's own."""
    from app.services import everyday

    root = tmp_path / "everyday-files"
    monkeypatch.setattr(everyday, "root", lambda: root)
    return root


@pytest.fixture(autouse=True)
def no_herdr(tmp_path, monkeypatch):  # noqa: ANN201
    """herdr as not running (no server at its socket), never the machine's
    own (app/ui/work_view.py)."""
    from app.sources.herdr import Herdr
    from app.ui import work_view

    nowhere = Herdr(tmp_path / "herdr.sock")
    monkeypatch.setattr(work_view, "herdr", lambda: nowhere)
    return nowhere


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


@pytest.fixture
def client(db):  # noqa: ANN201
    """The app over the `db` session, holding a CSRF token like a browser."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import create_app

    app = create_app()

    def override() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    client.get("/")  # obtain the CSRF cookie
    client.headers["X-CSRF"] = client.cookies.get("csrf", "")
    return client


@pytest.fixture
def live(app_db) -> Generator[str, None, None]:
    """The app served over HTTP from a thread, on a free port, over app_db."""
    import uvicorn

    from app.main import create_app

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # log_config=None as serve.py runs it: uvicorn leaves the process's logging alone.
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(), host="127.0.0.1", port=port, log_level="warning", log_config=None
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def page(live) -> Generator:
    """A Chromium page (skipped without one); any page error fails the test."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no Chromium for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        yield page
        browser.close()
        assert errors == []


@pytest.fixture
def phone(live) -> Generator:
    """A Chromium page as a phone's: its width, touched by a finger (skipped
    without one); any page error fails the test."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no Chromium for Playwright: {exc}")
        context = browser.new_context(
            viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        yield page
        browser.close()
        assert errors == []
