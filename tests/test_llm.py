"""Models: finding each provider's CLI, asking it who is signed in and
which models it offers (Claude Code's handshake, Codex's app-server, over a
stand-in of each), keeping that and the model each use runs on, the page
and Settings' row, and the chats running on what was chosen."""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app.models import Setting
from app.services import DomainError
from app.services import llm as llm_svc
from app.sources import llm
from app.sources.llm import AppServer, Model, ProbeFailed, Status

NOW = datetime(2026, 10, 4, 16, 39)
FAKE_APP_SERVER = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"

# Claude Code's initialize answer, as 2.1.289 gives it (trimmed).
SERVER_INFO = {
    "models": [
        {"value": "default", "resolvedModel": "claude-opus-5-5",
         "displayName": "Default (recommended)",
         "description": "Opus 5.5 · Best for everyday, complex tasks",
         "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
        {"value": "opus", "resolvedModel": "claude-opus-5-5", "displayName": "Opus 5.5",
         "description": "For complex work and everyday tasks",
         "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
        {"value": "sonnet", "resolvedModel": "claude-sonnet-5-5", "displayName": "Sonnet 5.5",
         "description": "Most efficient for simpler tasks",
         "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
        {"value": "haiku", "resolvedModel": "claude-haiku-4-5-20251001", "displayName": "Haiku 4.5",
         "description": "Fastest for quick answers"},
        {"value": "claude-opus-4-6", "resolvedModel": "claude-opus-4-6", "displayName": "Opus 4.6",
         "description": "Best for everyday, complex tasks",
         "supportedEffortLevels": ["low", "medium", "high", "max"]},
    ],
    "account": {"email": "oscar@example.com", "organization": "Oscar's Organization",
                "subscriptionType": "Claude Max", "apiProvider": "firstParty"},
}
AUTH = (
    '{\n  "loggedIn": true,\n  "authMethod": "claude.ai",\n'
    '  "email": "oscar@example.com",\n  "subscriptionType": "max"\n}'
)


def claude_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"")
    return exe


def claude_cli(auth: str = AUTH, code: int = 0):  # noqa: ANN201
    """Claude Code's answers to --version and auth status."""
    asked: list[list[str]] = []

    def run(args: list[str]) -> tuple[int, str]:
        asked.append(args[1:])
        if args[1:] == ["--version"]:
            return 0, "2.1.289 (Claude Code)\n"
        return code, auth

    run.asked = asked
    return run


# ---- Claude, through Claude Code ----


def test_claude_codes_models_each_once_its_pick_marked() -> None:
    models = llm.claude_models(SERVER_INFO)
    assert [(m.id, m.name) for m in models] == [
        ("claude-opus-5-5", "Opus 5.5"),
        ("claude-sonnet-5-5", "Sonnet 5.5"),
        ("claude-haiku-4-5-20251001", "Haiku 4.5"),
        ("claude-opus-4-6", "Opus 4.6"),
    ]
    assert [m.id for m in models if m.default] == ["claude-opus-5-5"]
    assert models[0].description == "For complex work and everyday tasks"
    assert models[2].efforts == ()
    assert models[3].efforts == ("low", "medium", "high", "max")
    assert llm.claude_models({}) == ()


@pytest.mark.parametrize(("auth", "account", "words"), [
    ({}, SERVER_INFO["account"], "oscar@example.com · Claude Max"),
    ({"email": "o@x.com", "subscriptionType": "pro"}, {}, "o@x.com · Claude Pro"),
    ({"authMethod": "api_key"}, {}, "An Anthropic API key"),
    ({}, {"email": "o@x.com", "apiProvider": "bedrock"}, "o@x.com · Amazon Bedrock"),
])
def test_who_claude_code_is_signed_in_as(auth, account, words) -> None:
    assert llm.claude_account(auth, {"account": account}) == words


def test_claude_code_signed_in_lists_its_models(tmp_path) -> None:
    exe = claude_exe(tmp_path)
    run = claude_cli()
    found = llm.probe_claude(str(exe), run=run, server_info=lambda path: SERVER_INFO, now=NOW)
    assert (found.state, found.version, found.cli) == ("ready", "2.1.289", str(exe))
    assert found.account == "oscar@example.com · Claude Max"
    assert found.default_model.id == "claude-opus-5-5"
    assert len(found.models) == 4 and found.message == ""
    assert run.asked == [["--version"], ["auth", "status", "--json"]]


def test_claude_code_signed_out(tmp_path) -> None:
    run = claude_cli('{"loggedIn": false, "authMethod": "none"}', code=1)
    exe = str(claude_exe(tmp_path))
    found = llm.probe_claude(exe, run=run, server_info=lambda path: {}, now=NOW)
    assert (found.state, found.account) == ("signed_out", "")
    assert found.message == "Claude Code is not signed in."


def test_claude_code_missing_or_not_answering(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    missing = llm.probe_claude(now=NOW)
    assert missing.state == "missing"
    assert missing.message == "Claude Code is not on this computer's PATH."
    elsewhere = llm.probe_claude(str(tmp_path / "nowhere.exe"), now=NOW)
    assert elsewhere.message == f"No Claude Code at {tmp_path / 'nowhere.exe'}."

    def broken(path: Path) -> dict:
        raise TimeoutError

    exe = str(claude_exe(tmp_path))
    failed = llm.probe_claude(exe, run=claude_cli(), server_info=broken, now=NOW)
    assert failed.state == "failed" and "would not list its models" in failed.message
    assert failed.account == "oscar@example.com · Claude Max"  # from auth status

    def dead(args: list[str]) -> tuple[int, str]:
        return 1, ""

    failed = llm.probe_claude(exe, run=dead, now=NOW)
    assert failed.state == "failed"
    assert failed.message == "Claude Code is installed but failed to run."


def test_npms_claude_cmd_leads_to_its_claude_exe(tmp_path) -> None:
    npm = tmp_path / "npm"
    exe = npm / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    (npm / "claude.cmd").write_text("")
    assert llm.claude_executable(str(npm / "claude.cmd")) == exe
    assert llm.claude_executable(str(exe)) == exe
    exe.unlink()
    with pytest.raises(ProbeFailed, match="choose its claude.exe"):
        llm.claude_executable(str(npm / "claude.cmd"))


# ---- OpenAI, through the Codex CLI ----


def codex(mode: str):  # noqa: ANN201
    """The app-server stand-in, started as the app starts codex's."""
    return lambda cli: AppServer([sys.executable, str(FAKE_APP_SERVER), mode], timeout=10)


def codex_version(args: list[str]) -> tuple[int, str]:
    assert args[1:] == ["--version"]
    return 0, "codex-cli 0.156.1\n"


def test_codex_signed_in_lists_its_models_page_by_page(tmp_path) -> None:
    cli = tmp_path / "codex.exe"
    cli.write_bytes(b"")
    found = llm.probe_openai(str(cli), run=codex_version, app_server=codex("ready"), now=NOW)
    assert (found.state, found.version, found.message) == ("ready", "0.156.1", "")
    assert found.account == "oscar@example.com · ChatGPT Pro"
    # The hidden one left out; the second page read.
    assert found.models == (
        Model("gpt-6-astra", "GPT-6 Astra", "Frontier agentic coding", ("low", "medium", "high"),
              "medium", default=True),
        Model("gpt-6-luna", "GPT-6 Luna", "Fast and light", ("low",), "low"),
    )


def test_codex_signed_out_refusing_or_silent(tmp_path) -> None:
    cli = tmp_path / "codex.exe"
    cli.write_bytes(b"")
    out = llm.probe_openai(str(cli), run=codex_version, app_server=codex("signed_out"), now=NOW)
    assert (out.state, out.message, out.models) == ("signed_out", "Codex CLI is not signed in.", ())
    refused = llm.probe_openai(str(cli), run=codex_version, app_server=codex("refuses"), now=NOW)
    assert refused.state == "failed"
    assert refused.message == "The Codex CLI refused model/list: models unavailable"

    def silent(path: str) -> AppServer:
        return AppServer([sys.executable, str(FAKE_APP_SERVER), "silent"], timeout=1)

    quiet = llm.probe_openai(str(cli), run=codex_version, app_server=silent, now=NOW)
    assert (quiet.state, quiet.message) == ("failed", "The Codex CLI did not answer in time.")


@pytest.mark.parametrize(("account", "words"), [
    ({"type": "chatgpt", "email": "o@x.com", "planType": "plus"}, "o@x.com · ChatGPT Plus"),
    ({"type": "chatgpt", "email": None, "planType": "unknown"}, "ChatGPT"),
    ({"type": "apiKey"}, "An OpenAI API key"),
    ({"type": "amazonBedrock"}, "Amazon Bedrock"),
])
def test_who_codex_is_signed_in_as(account, words) -> None:
    assert llm.codex_account(account) == words


def test_a_status_keeps_as_json() -> None:
    found = Status("claude", "ready", NOW, cli="c", version="1.2.3", account="a",
                   models=(Model("m", "M", "d", ("low",), "low", True),))
    assert Status.from_dict(found.to_dict()) == found


@pytest.mark.parametrize(("text", "found"), [
    ("2.1.289 (Claude Code)", "2.1.289"), ("codex-cli 0.156.1", "0.156.1"),
    ("codex-cli 0.157.0-alpha.2", "0.157.0-alpha.2"), ("nothing", ""),
])
def test_a_version_as_printed(text, found) -> None:
    assert llm.version(text) == found


# ---- the choices ----


def ready(provider: str, *models: Model, now: datetime = NOW) -> Status:
    return Status(provider, "ready", now, models=models)


OPUS = Model("claude-opus-5-5", "Opus 5.5", efforts=("low", "high", "max"), default=True)
HAIKU = Model("claude-haiku-4-5-20251001", "Haiku 4.5")


def test_a_use_runs_on_its_providers_default_until_chosen(db) -> None:
    assert llm_svc.choice(db, "nutrition") == llm_svc.Choice("claude", None, None, "")
    llm_svc.keep(db, [ready("claude", OPUS, HAIKU)])

    llm_svc.choose(db, "nutrition", "claude", "claude-opus-5-5", "high")
    assert llm_svc.choice(db, "nutrition") == llm_svc.Choice("claude", OPUS.id, "high", "")
    assert llm_svc.choice(db, "money").model is None  # each use its own

    # A model that takes no effort lets the effort go.
    llm_svc.choose(db, "nutrition", "claude", HAIKU.id, "high")
    assert llm_svc.choice(db, "nutrition").effort is None
    # The default again: the effort checked against the default's.
    llm_svc.choose(db, "nutrition", "claude", "", "max")
    assert llm_svc.choice(db, "nutrition") == llm_svc.Choice("claude", None, "max", "")

    with pytest.raises(DomainError, match="does not offer gpt-6"):
        llm_svc.choose(db, "nutrition", "claude", "gpt-6")
    with pytest.raises(DomainError, match="cannot run on OpenAI"):
        llm_svc.choose(db, "nutrition", "openai", "gpt-6-astra")
    with pytest.raises(DomainError, match="No use"):
        llm_svc.choose(db, "nowhere", "claude")


def test_a_choice_for_a_provider_the_use_no_longer_takes_is_let_go(db) -> None:
    chosen = {"uses": {"money": {"provider": "openai", "model": "x"}}}
    db.add(Setting(key=llm_svc.SETTING, value=chosen))
    db.flush()
    assert llm_svc.choice(db, "money") == llm_svc.Choice("claude", None, None, "")


def test_where_a_cli_is(db, tmp_path) -> None:
    exe = claude_exe(tmp_path)
    llm_svc.set_cli(db, "claude", f'  "{exe}" ')
    assert llm_svc.cli(db, "claude") == str(exe)
    assert llm_svc.choice(db, "nutrition").cli == str(exe)
    with pytest.raises(DomainError, match="There is no file at"):
        llm_svc.set_cli(db, "claude", str(tmp_path / "nowhere.exe"))
    llm_svc.set_cli(db, "claude", "")
    assert llm_svc.cli(db, "claude") == ""


def test_a_check_asks_every_provider_and_keeps_the_answers(db, tmp_path) -> None:
    exe = claude_exe(tmp_path)
    llm_svc.set_cli(db, "claude", str(exe))
    asked = []

    def probe(provider: str, configured: str) -> Status:
        asked.append((provider, configured))
        return ready(provider, OPUS) if provider == "claude" else Status(provider, "missing", NOW)

    assert llm_svc.stale(db)
    llm_svc.check(db, probe)
    assert sorted(asked) == [("claude", str(exe)), ("openai", "")]
    found = llm_svc.statuses(db)
    assert found["claude"].models == (OPUS,) and found["openai"].state == "missing"
    assert not llm_svc.stale(db, NOW + timedelta(minutes=4))
    assert llm_svc.stale(db, NOW + timedelta(minutes=6))


# ---- the page ----


@pytest.fixture
def page_client(client):  # noqa: ANN201
    from app.ui.models import get_probe

    def probe(provider: str, configured: str) -> Status:
        if provider == "claude":
            return Status(
                "claude", "ready", datetime.now(), cli="C:/npm/claude.exe", version="2.1.289",
                account="oscar@example.com · Claude Max", models=(OPUS, HAIKU),
            )
        message = "Codex CLI is not on this computer's PATH."
        return Status("openai", "missing", datetime.now(), message=message)

    client.app.dependency_overrides[get_probe] = lambda: probe
    yield client
    llm_svc.checking.wait(5)


def test_the_page_checks_then_shows_each_provider(page_client, db) -> None:
    first = page_client.get("/models").text
    assert "Not checked yet" in first and 'hx-trigger="every 2s"' in first  # checking
    llm_svc.checking.wait(5)
    page = page_client.get("/ui/models").text
    for words in ("Signed in", "Claude Code 2.1.289", "oscar@example.com · Claude Max",
                  "Opus 5.5", "claude-opus-5-5", "Haiku 4.5", "Default",
                  "Not installed", "npm install -g @openai/codex", "codex login",
                  "Nutrition&#39;s chat", ">Default · Opus 5.5<", "Check again"):
        assert words in page, words
    assert 'hx-trigger="every 2s"' not in page

    # Settings says the same in a word each.
    settings = page_client.get("/today").text
    assert 'href="/models"' in settings
    assert "Claude <span class=\"chip ok\">Signed in</span>" in settings
    assert "OpenAI <span class=\"chip neutral\">Not installed</span>" in settings


def test_choosing_a_model_and_its_effort_on_the_page(page_client, db) -> None:
    page_client.get("/models")
    llm_svc.checking.wait(5)
    drawn = page_client.post("/ui/models/use", data={
        "use": "money", "model": "claude:claude-opus-5-5", "effort": "max",
    }).text
    assert '<option value="claude:claude-opus-5-5" selected>' in drawn
    assert '<option value="max" selected>Max effort</option>' in drawn
    db.expire_all()
    assert llm_svc.choice(db, "money") == llm_svc.Choice("claude", "claude-opus-5-5", "max", "")
    # Haiku takes no effort: none offered.
    haiku = {"use": "money", "model": f"claude:{HAIKU.id}"}
    drawn = page_client.post("/ui/models/use", data=haiku).text
    assert "Spending&#39;s chat&#39;s reasoning effort" not in drawn


def test_saying_where_a_cli_is_on_the_page(page_client, db, tmp_path) -> None:
    page_client.get("/models")
    llm_svc.checking.wait(5)
    nowhere = {"provider": "openai", "path": str(tmp_path / "x.exe")}
    wrong = page_client.post("/ui/models/cli", data=nowhere)
    assert "There is no file at" in wrong.text
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"")
    page_client.post("/ui/models/cli", data={"provider": "openai", "path": str(exe)})
    llm_svc.checking.wait(5)
    db.expire_all()
    assert llm_svc.cli(db, "openai") == str(exe)
    assert f'value="{exe}"' in page_client.get("/ui/models").text


# ---- the chats run on what was chosen ----


def test_the_chats_run_on_the_model_chosen(db, tmp_path) -> None:
    from app.services import money_chat
    from app.services.claude_sdk import AgentEvent

    llm_svc.keep(db, [ready("claude", OPUS)])
    llm_svc.choose(db, "money", "claude", OPUS.id, "low")
    db.commit()
    seen = []

    async def agent(request):  # noqa: ANN001, ANN202
        seen.append(request.choice)
        yield AgentEvent("text", "Done")

    run = money_chat.start(db, date(2026, 10, 1), "Sort my month", agent=agent)
    run.wait(len(run.events), 5)
    while not run.finished:
        run.wait(len(run.events), 5)
    assert seen == [llm_svc.Choice("claude", OPUS.id, "low", "")]
