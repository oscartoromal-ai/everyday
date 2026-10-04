"""A machine installed without some modules (Health, Finances, Code): the
installer's install.toml read over the config, and the app leaving out their
pages, keys, Claude's tools, jobs and nudges (config.py's InstallConfig)."""

from datetime import date, datetime

import pydantic
import pytest
from fastmcp import Client

from app import config
from app.config import get_settings
from app.jobs.scheduler import create_scheduler
from app.mcp.server import create_mcp, mcp
from app.models import GarminDay, NudgeType
from app.services import money as money_svc
from app.services import nudges as nudges_svc
from app.ui.views import day_glance_ctx


@pytest.fixture
def leave_out(monkeypatch):  # noqa: ANN201
    """Install without the modules named."""

    def leave(*modules: str) -> None:
        monkeypatch.setattr(get_settings().install, "without", list(modules))

    return leave


@pytest.fixture
def client_without(leave_out, request):  # noqa: ANN201
    """The app (as `client`) of a machine installed without the modules named."""

    def build(*modules: str):  # noqa: ANN202
        leave_out(*modules)
        return request.getfixturevalue("client")

    return build


def home_config(tmp_path, monkeypatch, install: str) -> config.Settings:
    (tmp_path / "install.toml").write_text(install, encoding="utf-8")
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setitem(
        config.Settings.model_config,
        "toml_file",
        [config.REPO_ROOT / "config.toml", tmp_path / "config.toml", tmp_path / "install.toml"],
    )
    return config.Settings()


def test_every_module_is_in_unless_the_installer_left_it_out(tmp_path, monkeypatch) -> None:
    settings = home_config(tmp_path, monkeypatch, "")
    assert settings.install.without == []
    assert all(settings.installed(m) for m in ("planner", "projects", "health", "finances", "code"))

    settings = home_config(tmp_path, monkeypatch, '[install]\nwithout = ["finances"]\n')
    assert settings.install.without == ["finances"]
    assert not settings.installed("finances")
    assert settings.installed("health")
    assert settings.installed("planner")


def test_only_an_optional_module_can_be_left_out(tmp_path, monkeypatch) -> None:
    with pytest.raises(pydantic.ValidationError):
        home_config(tmp_path, monkeypatch, '[install]\nwithout = ["planner"]\n')


def test_without_finances_its_pages_are_gone(client_without) -> None:
    client = client_without("finances")
    for path in ("/spending", "/accounts", "/bills", "/goals"):
        assert client.get(path).status_code == 404, path
    page = client.get("/today")
    assert page.status_code == 200
    html = page.text
    assert 'data-section="finances"' not in html
    assert 'href="/spending"' not in html
    assert 'data-section="health"' in html and 'data-section="code"' in html
    # The number keys say the pages they reach, Spending's 7 no longer one.
    assert "<kbd>1</kbd>–<kbd>6</kbd>, <kbd>8</kbd></dt>" in html
    assert "<dd>Today, Calendar, Projects, Nutrition, Me, Garmin, Repositories</dd>" in html
    assert (
        "Not installed on this machine: Finances. Run the installer again to add it." in html
    )


def test_without_health_its_pages_and_keys_are_gone(client_without) -> None:
    client = client_without("health")
    for path in ("/nutrition", "/me", "/garmin", "/ui/me/context"):
        assert client.get(path).status_code == 404, path
    html = client.get("/today").text
    assert 'data-section="health"' not in html
    assert "<h3>Nutrition</h3>" not in html
    assert "<kbd>1</kbd>–<kbd>3</kbd>, <kbd>7</kbd>–<kbd>8</kbd></dt>" in html
    assert "<dd>Today, Calendar, Projects, Spending, Repositories</dd>" in html


def test_with_only_the_planner_the_settings_name_every_module_left_out(client_without) -> None:
    client = client_without("health", "finances", "code")
    html = client.get("/today").text
    assert "<dd>Today, Calendar, Projects</dd>" in html
    assert "<dt><kbd>1</kbd>–<kbd>3</kbd></dt>" in html
    assert (
        "Not installed on this machine: Health, Finances and Code. "
        "Run the installer again to add them." in html
    )
    assert client.get("/repositories").status_code == 404


def test_with_every_module_nothing_is_said_of_installing(client) -> None:
    html = client.get("/today").text
    assert "Not installed" not in html
    every = "Today, Calendar, Projects, Nutrition, Me, Garmin, Spending, Repositories"
    assert f"<dt><kbd>1</kbd>–<kbd>8</kbd></dt><dd>{every}</dd>" in html
    for path in ("/spending", "/me", "/garmin", "/nutrition", "/repositories"):
        assert client.get(path).status_code == 200, path


async def test_claude_gets_the_tools_of_the_modules_installed(app_db) -> None:
    async with Client(create_mcp(["finances", "code"])) as client:
        tools = {t.name for t in await client.list_tools()}
        instructions = client.initialize_result.instructions
    assert {"get_health_profile", "get_garmin", "list_tasks"} <= tools
    assert not {"get_finances", "list_repositories"} & tools
    assert "get_garmin" in instructions
    assert "get_finances" not in instructions and "list_repositories" not in instructions

    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
    assert {"get_health_profile", "get_garmin", "get_finances", "list_repositories"} <= tools


def test_without_health_today_has_no_watch_figures(db, leave_out) -> None:
    today = date.today()
    db.add(GarminDay(day=today, readiness=91, readiness_level="HIGH"))
    db.flush()
    now = datetime.combine(today, datetime.min.time())
    assert day_glance_ctx(db, today, now)["body"]

    leave_out("health")
    assert day_glance_ctx(db, today, now)["body"] == []


def test_without_finances_no_bill_nudges(db, leave_out) -> None:
    money_svc.save_bill(db, name="Netflix", cents=2299, cadence="monthly",
                        due=date(2026, 10, 14), match="netflix")
    now = datetime(2026, 10, 12, 9, 0)
    [nudge] = [n for n in nudges_svc.evaluate(db, now) if n.type == NudgeType.bill_due]

    leave_out("finances")
    # The one raised while Finances was in stops asking, and no other comes.
    assert nudge not in nudges_svc.active_nudges(db)
    money_svc.save_bill(db, name="Gym", cents=1500, cadence="monthly",
                        due=date(2026, 10, 13), match="gym")
    assert nudges_svc.evaluate(db, now) == []
    assert "Bills due" not in nudges_svc.build_morning_digest(db, now)


def test_without_health_and_code_their_syncs_never_run(leave_out) -> None:
    jobs = {j.id for j in create_scheduler().get_jobs()}
    assert {"garmin_sync", "github_sync"} <= jobs

    leave_out("health", "code")
    jobs = {j.id for j in create_scheduler().get_jobs()}
    assert not {"garmin_sync", "github_sync"} & jobs
    assert {"nudge_evaluation", "daily_backup"} <= jobs
