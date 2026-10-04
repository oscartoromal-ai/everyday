"""The agents the agent window chats with: Claude and Codex, each through its
own CLI on this machine's sign-in (Oscar's subscription; no API key). Where
each CLI is, whether it is signed in, and the model and effort each runs on
are Models' (services/llm.py): Claude is its Claude provider, Codex its
OpenAI one, and each agent a use of its own.

An agent is any callable from an AgentRequest to AgentEvents (the answer's
words as they come, and what it is doing meanwhile), so tests stand in a
fake. Each message is one stateless run, the chat so far in its prompt, as
Nutrition's and Spending's chats are. Neither has the planner's tools yet,
nor a shell or files of Oscar's: Claude may search and read the web, and
Codex works in a read-only sandbox from an empty folder.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import tempfile
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models import AgentKind
from app.services import claude_sdk
from app.services.claude_sdk import AgentEvent, AgentFailed, resolve_cli
from app.services.llm import Choice
from app.sources.llm import CLAUDE, OPENAI, Provider, find_cli

LABELS = {AgentKind.claude: "Claude", AgentKind.codex: "Codex"}
# Each agent's provider on Models, and its use there.
PROVIDERS: dict[AgentKind, Provider] = {AgentKind.claude: CLAUDE, AgentKind.codex: OPENAI}
USES = {AgentKind.claude: "agent-claude", AgentKind.codex: "agent-codex"}


@dataclass(frozen=True)
class AgentRequest:
    now: datetime
    message: str
    # The chat so far, oldest first: ("oscar" | "agent", text).
    transcript: list[tuple[str, str]] = field(default_factory=list)
    # What it runs with, as chosen on Models (None: the provider's default).
    choice: Choice | None = None


Agent = Callable[[AgentRequest], AsyncIterator[AgentEvent]]


def instructions(kind: AgentKind) -> str:
    """Who the agent is, where, and what it can and cannot reach."""
    reach = (
        "You can search and read the web."
        if kind == AgentKind.claude
        else "You work in a read-only sandbox, from an empty folder that is not his."
    )
    return f"""\
You are {LABELS[kind]}, talking with Oscar in the agent window of his personal \
planner app, a desktop app on his Windows machine. The window sits at the side \
of whatever page of the app he has open.

You have no tools into his planner yet (its tasks, projects, calendar, notes), \
nor his files. {reach} When something would need his own data, say so plainly \
rather than guess it.

Answering:
- Be brief and concrete: a few short paragraphs at most, unless he asks for more.
- Write Markdown (paragraphs, lists, `code`, fenced code blocks). The window is \
narrow, about 400px, so keep tables to two or three short columns.
- Never invent facts about him. When you need to know something, ask."""


def build_prompt(request: AgentRequest, kind: AgentKind) -> str:
    """The run's prompt: when, the chat so far, then his message."""
    now = request.now
    lines = [f"Now: {now:%A} {now.day} {now:%B %Y, %H:%M}."]
    if request.transcript:
        lines += ["", "Earlier in this chat:"]
        for role, text in request.transcript:
            lines += ["", f"{'Oscar' if role == 'oscar' else 'You'}:", text]
    lines += ["", "Oscar's new message:", "", request.message]
    return "\n".join(lines)


def room() -> Path:
    """The folder the agents run in: one of their own, empty."""
    path = Path(tempfile.gettempdir()) / "personal-calendar-agent"
    path.mkdir(exist_ok=True)
    return path


def _choice(request: AgentRequest, kind: AgentKind) -> Choice:
    return request.choice or Choice(PROVIDERS[kind].key, None, None, "")


# ---- Claude, through the Claude Agent SDK (claude_sdk) ----

WEB = ["WebSearch", "WebFetch"]


def _claude_status(tool: str, tool_input: dict[str, Any]) -> str:
    if tool == "WebSearch":
        return "Searching the web"
    if tool == "WebFetch":
        return "Reading a page"
    return "Working"


async def claude_agent(request: AgentRequest) -> AsyncIterator[AgentEvent]:
    """Claude: the answer as it is written, and a status for each tool call.
    Raises AgentFailed when the run fails."""
    from claude_agent_sdk import ClaudeAgentOptions

    choice = _choice(request, AgentKind.claude)
    options = ClaudeAgentOptions(
        system_prompt=instructions(AgentKind.claude),
        model=choice.model,
        effort=choice.effort,
        cwd=room(),
        cli_path=resolve_cli(choice.cli),
        tools=WEB,
        allowed_tools=WEB,
        permission_mode="dontAsk",
        # Nothing of the machine's own: no settings, CLAUDE.md, skills or MCP servers.
        setting_sources=[],
        strict_mcp_config=True,
        include_partial_messages=True,
        max_turns=20,
    )
    async for event in claude_sdk.run(
        build_prompt(request, AgentKind.claude), options, _claude_status
    ):
        yield event


# ---- Codex, through `codex exec --json` ----

CODEX_MISSING = (
    f"Codex is not installed here: install it (`{OPENAI.install}`), "
    f"then sign in with `{OPENAI.sign_in}`, or say where it is on Models"
)
CODEX_SIGNED_OUT = f"Codex is not signed in here: run `{OPENAI.sign_in}`"


def resolve_codex(configured: str = "") -> Path:
    """The Codex executable to run: where Models says it is, else `codex` on
    PATH (sources/llm.py). npm's codex.cmd shim leads to the native
    codex.exe npm installed beside it, so a run that is cut short stops
    Codex itself, not only the shell in front of it."""
    found = find_cli(OPENAI, configured)
    if found is None:
        if configured:
            raise AgentFailed(f"No Codex at {configured}: say where it is on Models")
        raise AgentFailed(CODEX_MISSING)
    path = Path(found)
    if path.suffix.lower() in (".cmd", ".bat"):
        modules = path.parent / "node_modules"
        for base in (modules / "@openai" / "codex" / "node_modules", modules):
            native = sorted(base.glob("@openai/codex-win32-*/vendor/*/bin/codex.exe"))
            if native:
                return native[0]
    return path


def codex_args(exe: Path, folder: Path, choice: Choice) -> list[str]:
    """`codex exec`, its events as JSON lines, its prompt read from stdin (so
    no words of Oscar's are ever on a command line)."""
    args = [
        str(exe),
        "exec",
        "--json",
        "--color",
        "never",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--cd",
        str(folder),
    ]
    if choice.model:
        args += ["--model", choice.model]
    if choice.effort:
        args += ["--config", f'model_reasoning_effort="{choice.effort}"']
    return [*args, "-"]


def _short(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _codex_failure(message: str) -> str:
    if "401" in message or "Unauthorized" in message:
        return CODEX_SIGNED_OUT
    return f"Codex stopped with an error: {message}"


class CodexReader:
    """Codex's JSON events as AgentEvents: an item it starts says what it is
    doing, and each message it completes is said whole (Codex sends no
    words before a message is done)."""

    def __init__(self) -> None:
        self.said = False
        self.finished = False
        # Why its turn failed, once it has: Codex exits right after.
        self.failure: str | None = None

    def read(self, event: dict[str, Any]) -> list[AgentEvent]:
        kind = event.get("type")
        if kind == "turn.failed":
            self.failure = _codex_failure((event.get("error") or {}).get("message", ""))
            return []
        if kind == "turn.completed":
            self.finished = True
            return []
        if kind == "error":
            # Codex says so while it retries; turn.failed follows if it gives up.
            message = event.get("message", "")
            return (
                [AgentEvent("status", "Reconnecting")] if message.startswith("Reconnecting") else []
            )
        item = event.get("item") or {}
        item_type = item.get("type") or item.get("item_type")
        if kind == "item.started":
            status = {
                "reasoning": "Thinking",
                "web_search": "Searching the web",
                "file_change": "Changing files",
                "todo_list": "Planning",
            }.get(item_type)
            if item_type == "command_execution":
                status = f"Running {_short(item.get('command', 'a command'))}"
            elif item_type == "mcp_tool_call":
                status = f"Using {item.get('tool', 'a tool')}"
            return [AgentEvent("status", status)] if status else []
        if kind == "item.completed" and item_type in ("agent_message", "assistant_message"):
            text = item.get("text", "")
            if not text:
                return []
            events = [AgentEvent("text", "\n\n")] if self.said else []
            self.said = True
            return [*events, AgentEvent("text", text)]
        return []


async def codex_agent(request: AgentRequest) -> AsyncIterator[AgentEvent]:
    """Codex: each message as it completes, and a status for what it is
    doing. Raises AgentFailed when the run fails."""
    choice = _choice(request, AgentKind.codex)
    exe = resolve_codex(choice.cli)
    folder = room()
    prompt = f"{instructions(AgentKind.codex)}\n\n{build_prompt(request, AgentKind.codex)}"
    try:
        process = await asyncio.create_subprocess_exec(
            *codex_args(exe, folder, choice),
            cwd=folder,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # One event is one line, and a long answer is one long line.
            limit=16 * 1024 * 1024,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise AgentFailed(f"Codex could not run: {exc}") from exc
    # Its log, read as it comes so it never fills the pipe, its last lines
    # kept to say why it stopped.
    log: deque[str] = deque(maxlen=5)

    async def drain() -> None:
        assert process.stderr is not None
        async for raw in process.stderr:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                log.append(line)

    draining = asyncio.create_task(drain())
    reader = CodexReader()
    ended = False  # its output read to the end, so Codex is done
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        async for raw in process.stdout:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            for agent_event in reader.read(event):
                yield agent_event
        ended = True
        await draining
    finally:
        draining.cancel()
        # A run cut short stops Codex; either way what is left of its output
        # is read, so its pipes close with it.
        if not ended and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.communicate()
    if reader.failure is not None:
        raise AgentFailed(reader.failure)
    if process.returncode != 0 and not reader.finished:
        detail = log[-1] if log else f"it exited with {process.returncode}"
        raise AgentFailed(f"Codex stopped with an error: {detail}")




AGENTS: dict[AgentKind, Agent] = {AgentKind.claude: claude_agent, AgentKind.codex: codex_agent}
