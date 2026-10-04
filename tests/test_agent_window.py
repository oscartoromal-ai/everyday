"""The agent window: chats with Claude or Codex beside every page, the agent
chosen per chat, the model each runs on chosen on Models, answers streamed
and saved, and an agent that is not here saying why. Stand-ins answer for
the agents and for Models' check; Codex's own JSON events are read as
`codex exec --json` writes them."""

import json
from datetime import datetime

import pytest

from app.models import AgentKind, AgentRole
from app.services import agent_window as window_svc
from app.services import agents
from app.services import llm as llm_svc
from app.services.agents import AgentRequest, CodexReader, build_prompt
from app.services.claude_sdk import AgentEvent, AgentFailed
from app.services.llm import Choice
from app.sources import llm
from app.sources.llm import Model, Status


def stand_in(words: str = "Hello **there**."):  # noqa: ANN201
    async def agent(request: AgentRequest):  # noqa: ANN202
        yield AgentEvent("status", "Thinking it over")
        yield AgentEvent("text", words)

    return agent


def failing():  # noqa: ANN201
    async def agent(request: AgentRequest):  # noqa: ANN202
        yield AgentEvent("text", "Half an answer")
        raise AgentFailed("Codex is not signed in here: run `codex login`")

    return agent


def status(provider: str, state: str = "ready", **more) -> Status:  # noqa: ANN003
    return Status(provider, state, datetime(2026, 10, 4, 9, 0), **more)


def checked(db, *found: Status) -> None:  # noqa: ANN001
    """Models' last check said so."""
    llm_svc.keep(db, list(found))
    db.commit()


@pytest.fixture
def chat_client(client):  # noqa: ANN001, ANN201
    """The app with stand-in agents (`use`), and Models' check of a provider
    answering as `probed` says, each provider asked kept in `asked`."""
    from app.ui.agent_window import get_agents
    from app.ui.models import get_probe

    def use(**by_kind) -> None:  # noqa: ANN003
        roster = {AgentKind(k): a for k, a in by_kind.items()}
        client.app.dependency_overrides[get_agents] = lambda: roster

    client.probed = {}
    client.asked = []

    def probe(provider: str, configured: str = "") -> Status:
        client.asked.append(provider)
        return client.probed.get(provider) or status(provider)

    client.app.dependency_overrides[get_probe] = lambda: probe
    client.use = use
    return client


def events_of(response) -> list[dict]:  # noqa: ANN001
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_every_page_has_the_window_with_its_agent_and_the_sidebars_button(client) -> None:
    page = client.get("/today").text
    assert 'id="agent-panel"' in page
    assert 'class="rail-button agent-open"' in page and 'aria-keyshortcuts="A"' in page
    assert '<option value="claude" selected>Claude</option>' in page
    assert ">Default model</a>" in page  # never checked: Claude's own default
    assert "Ask Claude anything" in page
    # Collapsed until opened: the window starts closed (pc-agent, before paint).
    assert 'data-agent="open"' not in page


def test_it_runs_on_the_model_chosen_on_models_named_as_its_cli_lists_it(
    chat_client, db
) -> None:
    opus = Model("claude-opus-5-5", "Claude Opus 5.5", efforts=("low", "high"), default=True)
    sonnet = Model("claude-sonnet-5-5", "Claude Sonnet 5.5", efforts=("low", "high"))
    checked(db, status("claude", models=(opus, sonnet)))
    assert ">Default · Claude Opus 5.5</a>" in chat_client.get("/today").text

    # Each agent is a use of its own on Models.
    assert {"agent-claude", "agent-codex"} <= {u.key for u in llm_svc.uses()}
    chat_client.post(
        "/ui/models/use",
        data={"use": "agent-claude", "model": "claude:claude-sonnet-5-5", "effort": "high"},
    )
    assert ">Claude Sonnet 5.5 · High</a>" in chat_client.get("/today").text

    heard: list[AgentRequest] = []

    async def listening(request: AgentRequest):  # noqa: ANN202
        heard.append(request)
        yield AgentEvent("text", "Hi.")

    chat_client.use(claude=listening)
    chat_client.post("/ui/agent/chat", data={"message": "Hi", "agent": "claude"})
    assert heard[0].choice == Choice("claude", "claude-sonnet-5-5", "high", "")


def test_a_message_streams_the_answer_and_both_are_kept(chat_client, db) -> None:
    chat_client.use(claude=stand_in())
    response = chat_client.post("/ui/agent/chat", data={"message": "Hi", "agent": "claude"})
    assert response.status_code == 200, response.text
    assert events_of(response) == [
        {"type": "status", "text": "Thinking it over"},
        {"type": "text", "text": "Hello **there**."},
        {"type": "done", "failed": False},
    ]
    db.expire_all()
    chat = window_svc.current(db)
    assert chat.agent == AgentKind.claude
    said = window_svc.messages(db, chat)
    assert [(m.role, m.text) for m in said] == [
        (AgentRole.oscar, "Hi"),
        (AgentRole.agent, "Hello **there**."),
    ]
    log = chat_client.get("/ui/agent/log").text
    assert "<strong>there</strong>" in log and ">Claude <" in log


def test_the_next_message_carries_the_chat_so_far(chat_client) -> None:
    heard: list[AgentRequest] = []

    async def listening(request: AgentRequest):  # noqa: ANN202
        heard.append(request)
        yield AgentEvent("text", "Noted.")

    chat_client.use(claude=listening)
    chat_client.post("/ui/agent/chat", data={"message": "My cat is Miso", "agent": "claude"})
    chat_client.post("/ui/agent/chat", data={"message": "Her name?", "agent": "claude"})
    assert heard[1].transcript == [("oscar", "My cat is Miso"), ("agent", "Noted.")]
    prompt = build_prompt(heard[1], AgentKind.claude)
    order = [prompt.index(w) for w in ("My cat is Miso", "Noted.", "Her name?")]
    assert order == sorted(order)


def test_a_failed_answer_keeps_what_was_said_and_why(chat_client, db) -> None:
    chat_client.use(claude=failing())
    response = chat_client.post("/ui/agent/chat", data={"message": "Hi", "agent": "claude"})
    assert events_of(response)[-1] == {"type": "done", "failed": True}
    db.expire_all()
    answer = window_svc.messages(db, window_svc.current(db))[-1]
    assert answer.failed and answer.text.startswith("Half an answer\n\n")
    assert "Did not finish" in chat_client.get("/ui/agent/log").text


def test_choosing_another_agent_starts_a_chat_with_it_and_back_finds_the_first(
    chat_client, db
) -> None:
    chat_client.use(claude=stand_in(), codex=stand_in("From Codex."))
    chat_client.post("/ui/agent/chat", data={"message": "Hi", "agent": "claude"})
    first = window_svc.current(db).id

    window = chat_client.post("/ui/agent/agent", data={"agent": "codex"}).text
    assert '<option value="codex" selected>Codex</option>' in window
    assert "Ask Codex anything" in window
    assert window_svc.current(db).id != first

    # Back to Claude before a word to Codex: Claude's chat, as it was.
    window = chat_client.post("/ui/agent/agent", data={"agent": "claude"}).text
    assert window_svc.current(db).id == first
    assert "Hello <strong>there</strong>." in window


def test_new_chat_starts_afresh_with_the_same_agent_and_never_piles_up(chat_client, db) -> None:
    chat_client.use(codex=stand_in("From Codex."))
    chat_client.post("/ui/agent/agent", data={"agent": "codex"})
    chat_client.post("/ui/agent/chat", data={"message": "Hi", "agent": "codex"})
    window = chat_client.post("/ui/agent/new").text
    assert "Ask Codex anything" in window and "From Codex." not in window
    fresh = window_svc.current(db).id
    chat_client.post("/ui/agent/new")
    assert window_svc.current(db).id == fresh  # still the one empty chat


def test_an_agent_not_here_says_why_and_takes_no_message(chat_client, db) -> None:
    missing = status("openai", "missing", message="Codex CLI is not on this computer's PATH.")
    checked(db, missing)
    page = chat_client.get("/today").text
    # Listed with why, while Claude is the chosen one.
    assert '<option value="codex">Codex · Not installed</option>' in page

    # Turned to, it is asked again; still not there, it says why.
    chat_client.probed["openai"] = missing
    window = chat_client.post("/ui/agent/agent", data={"agent": "codex"}).text
    assert chat_client.asked == ["openai"]
    assert '<span class="chip warn">Not installed</span>' in window
    assert f"<code>{llm.OPENAI.install}</code>" in window
    assert '<a href="/models">Open Models</a>' in window
    assert "disabled" in window.split('name="message"')[1].split(">")[0]

    chat_client.use(codex=stand_in())
    refused = chat_client.post("/ui/agent/chat", data={"message": "Hi", "agent": "codex"})
    assert refused.status_code == 422
    assert "not on this computer" in refused.json()["detail"]


def test_an_agent_signed_in_since_is_asked_again_before_a_message(chat_client, db) -> None:
    checked(db, status("openai", "signed_out"))
    assert "Codex · Not signed in" in chat_client.get("/today").text
    chat_client.use(codex=stand_in("Signed in now."))
    response = chat_client.post("/ui/agent/chat", data={"message": "Hi", "agent": "codex"})
    assert response.status_code == 200
    assert events_of(response)[-1] == {"type": "done", "failed": False}
    assert chat_client.asked == ["openai"]
    # Kept for Models too.
    db.expire_all()
    assert llm_svc.status(db, "openai").state == "ready"


def test_an_agent_here_or_never_checked_is_not_asked_again(chat_client) -> None:
    chat_client.use(claude=stand_in(), codex=stand_in())
    chat_client.post("/ui/agent/agent", data={"agent": "codex"})
    chat_client.post("/ui/agent/chat", data={"message": "Hi", "agent": "codex"})
    assert chat_client.asked == []


def test_only_codex_here_starts_the_first_chat_with_codex(chat_client, db) -> None:
    checked(db, status("claude", "missing"), status("openai"))
    assert '<option value="codex" selected>Codex</option>' in chat_client.get("/today").text


def test_an_empty_message_is_refused(chat_client) -> None:
    chat_client.use(claude=stand_in())
    refused = chat_client.post("/ui/agent/chat", data={"message": "  ", "agent": "claude"})
    assert refused.status_code == 422


# ---- Codex's events, as `codex exec --json` writes them ----


def test_codex_events_become_statuses_and_whole_messages() -> None:
    reader = CodexReader()
    lines = [
        {"type": "thread.started", "thread_id": "01a1"},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"id": "item_0", "type": "reasoning", "text": ""}},
        {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "Get-ChildItem -Recurse -Filter *.md",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "item_2", "type": "agent_message", "text": "One."},
        },
        {
            "type": "item.completed",
            "item": {"id": "item_3", "type": "agent_message", "text": "Two."},
        },
        {"type": "turn.completed", "usage": {"input_tokens": 10}},
    ]
    events = [e for line in lines for e in reader.read(line)]
    assert events == [
        AgentEvent("status", "Thinking"),
        AgentEvent("status", "Running Get-ChildItem -Recurse -Filter *.md"),
        AgentEvent("text", "One."),
        AgentEvent("text", "\n\n"),
        AgentEvent("text", "Two."),
    ]
    assert reader.finished and reader.failure is None


def test_codex_retrying_then_failing_unauthorised_says_to_sign_in() -> None:
    # As Codex 0.160 wrote them, signed out.
    reader = CodexReader()
    lines = [
        {"type": "error", "message": "Reconnecting... 2/5 (unexpected status 401 Unauthorized)"},
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "error",
                "message": "Falling back from WebSockets to HTTPS",
            },
        },
        {"type": "error", "message": "unexpected status 401 Unauthorized: Missing bearer"},
        {"type": "turn.failed", "error": {"message": "unexpected status 401 Unauthorized"}},
    ]
    events = [e for line in lines for e in reader.read(line)]
    assert events == [AgentEvent("status", "Reconnecting")]
    assert reader.failure == agents.CODEX_SIGNED_OUT


def test_codex_runs_from_its_native_exe_with_the_prompt_on_stdin(tmp_path, monkeypatch) -> None:
    shim = tmp_path / "codex.cmd"
    shim.write_text("@echo off\n")
    native = (
        tmp_path / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai"
        / "codex-win32-x64" / "vendor" / "x86_64-pc-windows-msvc" / "bin" / "codex.exe"
    )  # fmt: skip
    native.parent.mkdir(parents=True)
    native.write_bytes(b"")
    monkeypatch.setattr(llm.shutil, "which", lambda name: str(shim) if name == "codex" else None)
    exe = agents.resolve_codex()
    assert exe == native
    args = agents.codex_args(exe, tmp_path, Choice("openai", None, None, ""))
    assert args[1:3] == ["exec", "--json"] and "--model" not in args
    assert args[args.index("--sandbox") + 1] == "read-only" and args[-1] == "-"
    chosen = agents.codex_args(exe, tmp_path, Choice("openai", "gpt-6", "high", ""))
    assert chosen[-5:] == ["--model", "gpt-6", "--config", 'model_reasoning_effort="high"', "-"]


def test_no_codex_says_how_to_install_it(monkeypatch) -> None:
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    with pytest.raises(AgentFailed, match="npm install -g @openai/codex"):
        agents.resolve_codex()


def test_the_window_is_told_when_the_prompt_was_written() -> None:
    request = AgentRequest(now=datetime(2026, 10, 4, 9, 5), message="Hello")
    prompt = build_prompt(request, AgentKind.codex)
    assert prompt.startswith("Now: Sunday 4 October 2026, 09:05.")
    assert prompt.endswith("Oscar's new message:\n\nHello")
