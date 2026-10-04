"""The LLM providers on this machine, and the models each offers: Claude,
through Claude Code, and OpenAI, through the Codex CLI.

Each is asked as T3 Code asks it, through its own CLI, signed in its own
way, so the app keeps no API key: whether it is installed and at which
version, who it is signed in as, and the models it offers, as the CLI
itself lists them (so a new model shows up when the CLI knows it):

- Claude Code: `claude --version`, `claude auth status --json`, then its
  initialize handshake through the Agent SDK, which answers with the
  account and the models, without a prompt sent (nothing is spent).
- Codex: `codex --version`, then a short-lived `codex app-server`, spoken
  to in its JSON-RPC (a JSON object a line): initialize, `account/read`
  and `model/list`, page by page.

Only I/O lives here: services/llm.py keeps what comes back and the choices
made from it. Tests stand in each CLI with a function, and the app-server
with a script of their own.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

# How long one command may take (a version, a sign-in), and a whole
# conversation with a CLI (Claude Code's handshake, Codex's app-server).
COMMAND_TIMEOUT_S = 15
SESSION_TIMEOUT_S = 30


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    # The CLI the app reaches it through, and the command that runs it.
    program: str
    command: str
    install: str
    sign_in: str


CLAUDE = Provider(
    key="claude", name="Claude", program="Claude Code", command="claude",
    install="npm install -g @anthropic-ai/claude-code", sign_in="claude auth login",
)
OPENAI = Provider(
    key="openai", name="OpenAI", program="Codex CLI", command="codex",
    install="npm install -g @openai/codex", sign_in="codex login",
)
PROVIDERS = (CLAUDE, OPENAI)
BY_KEY = {p.key: p for p in PROVIDERS}


@dataclass(frozen=True)
class Model:
    # As the CLI takes it ("claude-opus-5-5", "gpt-6-astra").
    id: str
    name: str
    description: str = ""
    # The reasoning efforts it takes, least first, and the one it uses
    # unless told ("" when the CLI does not say).
    efforts: tuple[str, ...] = ()
    default_effort: str = ""
    # The provider's own pick, used when none is chosen.
    default: bool = False


State = Literal["ready", "signed_out", "missing", "failed"]


@dataclass(frozen=True)
class Status:
    """A provider as last checked: ready (installed and signed in),
    signed_out, missing (no CLI found) or failed (and why)."""

    provider: str
    state: State
    checked_at: datetime
    cli: str = ""
    version: str = ""
    # Who it is signed in as: "oscar@example.com · Claude Max".
    account: str = ""
    models: tuple[Model, ...] = ()
    message: str = ""

    @property
    def default_model(self) -> Model | None:
        return next((m for m in self.models if m.default), None)

    def model(self, model_id: str) -> Model | None:
        return next((m for m in self.models if m.id == model_id), None)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checked_at"] = self.checked_at.isoformat(timespec="seconds")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Status:
        models = tuple(
            Model(**{**m, "efforts": tuple(m.get("efforts") or ())})
            for m in data.get("models") or ()
        )
        return cls(**{
            **data, "models": models, "checked_at": datetime.fromisoformat(data["checked_at"]),
        })


class ProbeFailed(Exception):
    """A CLI did not answer as expected; the message says why, to Oscar."""


# ---- running a CLI ----


# Runs a command; returns its exit code and what it printed.
Runner = Callable[[list[str]], tuple[int, str]]

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(args: list[str]) -> tuple[int, str]:
    done = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=COMMAND_TIMEOUT_S, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
    )
    return done.returncode, done.stdout + done.stderr


def find_cli(provider: Provider, configured: str = "") -> str | None:
    """The CLI's path: as configured, else on PATH."""
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which(provider.command)


def claude_executable(path: str) -> Path:
    """The Claude Code executable the Agent SDK can run. Windows will only
    run a native claude.exe for it (a .cmd would go through cmd.exe), so
    npm's claude.cmd shim leads to the claude.exe npm installed beside it."""
    found = Path(path)
    if found.suffix.lower() not in (".cmd", ".bat", ".ps1"):
        return found
    native = found.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    if not native.is_file():
        raise ProbeFailed(
            f"Claude Code at {found} is a script the app cannot run: choose its claude.exe instead."
        )
    return native


def version(text: str) -> str:
    """The version a CLI printed ("2.1.289 (Claude Code)", "codex-cli 0.156.1")."""
    found = re.search(r"\bv?(\d+\.\d+\.\d+(?:[-+.][\w.]+)?)", text)
    return found.group(1) if found else ""


def _version(run: Runner, cli: str, provider: Provider) -> str:
    try:
        code, out = run([cli, "--version"])
    except subprocess.TimeoutExpired as exc:
        raise ProbeFailed(f"{provider.program} did not answer in time.") from exc
    except OSError as exc:
        raise ProbeFailed(f"{provider.program} would not start: {exc}") from exc
    if code != 0:
        raise ProbeFailed(f"{provider.program} is installed but failed to run.")
    return version(out)


# ---- Claude, through Claude Code ----


# Reads Claude Code's initialize answer (its account and models) for this
# executable.
ServerInfo = Callable[[Path], dict[str, Any]]


def _server_info(executable: Path) -> dict[str, Any]:
    """Claude Code's initialize answer, through the Agent SDK: a session
    opened and closed with no prompt, so nothing reaches the model."""
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    options = ClaudeAgentOptions(
        cli_path=executable, tools=[], setting_sources=[], mcp_servers={},
        strict_mcp_config=True, env={"CLAUDE_CODE_AUTO_CONNECT_IDE": "0"},
    )

    async def ask() -> dict[str, Any]:
        async with asyncio.timeout(SESSION_TIMEOUT_S), ClaudeSDKClient(options=options) as client:
            return await client.get_server_info() or {}

    return asyncio.run(ask())


def claude_models(info: dict[str, Any]) -> tuple[Model, ...]:
    """The models in Claude Code's initialize answer, each once by the id
    its entry resolves to; its "default" entry is no model of its own but
    names the one Claude Code picks."""
    entries = [e for e in info.get("models") or () if isinstance(e, dict) and e.get("value")]
    picked = next((e.get("resolvedModel") for e in entries if e["value"] == "default"), None)
    models: dict[str, Model] = {}
    for entry in entries:
        if entry["value"] == "default":
            continue
        model_id = entry.get("resolvedModel") or entry["value"]
        if model_id in models:
            continue
        models[model_id] = Model(
            id=model_id,
            name=entry.get("displayName") or model_id,
            description=entry.get("description") or "",
            efforts=tuple(entry.get("supportedEffortLevels") or ()),
            default=model_id == picked,
        )
    return tuple(models.values())


def claude_account(auth: dict[str, Any], info: dict[str, Any]) -> str:
    """Who Claude Code is signed in as, in words: its email and plan."""
    account = info.get("account") or {}
    email = account.get("email") or auth.get("email") or ""
    provider = account.get("apiProvider") or auth.get("apiProvider") or ""
    if provider == "bedrock":
        how = "Amazon Bedrock"
    elif provider == "vertex":
        how = "Google Vertex AI"
    elif auth.get("authMethod") in ("api_key", "apiKey") or account.get("tokenSource") == "apiKey":
        how = "An Anthropic API key"
    elif account.get("subscriptionType"):
        how = account["subscriptionType"]
    elif auth.get("subscriptionType"):
        how = f"Claude {str(auth['subscriptionType']).title()}"
    else:
        how = ""
    return " · ".join(part for part in (email, how) if part)


def probe_claude(
    configured: str = "", *, run: Runner = _run, server_info: ServerInfo = _server_info,
    now: datetime | None = None,
) -> Status:
    now = now or datetime.now()
    cli = find_cli(CLAUDE, configured)
    if cli is None:
        return Status(CLAUDE.key, "missing", now, message=_missing(CLAUDE, configured))
    try:
        executable = claude_executable(cli)
        found = _version(run, str(executable), CLAUDE)
        auth = _claude_auth(run, executable)
    except ProbeFailed as exc:
        return Status(CLAUDE.key, "failed", now, cli=cli, message=str(exc))
    signed_in = bool(auth.get("loggedIn"))
    info: dict[str, Any] = {}
    message = ""
    try:
        info = server_info(executable)
    except Exception as exc:  # the SDK's own errors, a timeout, the CLI dying
        log.warning("Claude Code's handshake failed: %s", exc)
        message = "Claude Code would not list its models. Check again in a moment."
    state: State = "ready" if signed_in else "signed_out"
    if signed_in and message:
        state = "failed"
    return Status(
        CLAUDE.key, state, now, cli=str(executable), version=found,
        account=claude_account(auth, info) if signed_in else "",
        models=claude_models(info),
        message=message if signed_in else _signed_out(CLAUDE),
    )


def _claude_auth(run: Runner, executable: Path) -> dict[str, Any]:
    """`claude auth status --json`: whether it is signed in, and how. It
    exits 1, still answering, when signed out."""
    try:
        _, out = run([str(executable), "auth", "status", "--json"])
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProbeFailed(f"Claude Code would not say who it is signed in as: {exc}") from exc
    try:
        answer = json.loads(out[out.index("{"):out.rindex("}") + 1])
    except ValueError as exc:
        raise ProbeFailed("Claude Code would not say who it is signed in as.") from exc
    return answer if isinstance(answer, dict) else {}


# ---- OpenAI, through the Codex CLI ----


class AppServer:
    """A `codex app-server` running for one conversation: a request, its
    answer, a JSON object a line each way. A context manager: the process
    goes at the end, its children with it."""

    def __init__(self, args: list[str], timeout: float = SESSION_TIMEOUT_S) -> None:
        self._deadline = time.monotonic() + timeout
        self._next_id = 0
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._process = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
        threading.Thread(target=self._read, name="codex-app-server", daemon=True).start()

    def _read(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def __enter__(self) -> AppServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _send(self, message: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()
        except OSError as exc:
            raise ProbeFailed("The Codex CLI stopped answering.") from exc

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"method": method, **({"params": params} if params is not None else {})})

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """The answer to a request; its notifications and requests to the
        app on the way are passed over."""
        self._next_id += 1
        asked = self._next_id
        self._send({"id": asked, "method": method, "params": params or {}})
        while True:
            remaining = self._deadline - time.monotonic()
            try:
                line = self._lines.get(timeout=max(remaining, 0))
            except queue.Empty as exc:
                raise ProbeFailed("The Codex CLI did not answer in time.") from exc
            if line is None:
                raise ProbeFailed("The Codex CLI stopped before it answered.")
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict) or message.get("id") != asked or "method" in message:
                continue
            if "error" in message:
                error = message["error"] or {}
                reason = error.get("message") or error
                raise ProbeFailed(f"The Codex CLI refused {method}: {reason}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def close(self) -> None:
        if self._process.stdin is not None:
            with contextlib.suppress(OSError):
                self._process.stdin.close()
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_tree(self._process)


def _kill_tree(process: subprocess.Popen) -> None:
    """The process and what it started: npm's codex.cmd runs codex under
    cmd.exe, so killing the first alone would leave codex running."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, creationflags=_NO_WINDOW, check=False,
        )
    else:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        log.warning("codex app-server (pid %s) would not stop", process.pid)


# Starts the app-server conversation for this CLI.
AppServerFactory = Callable[[str], AppServer]


def _app_server(cli: str) -> AppServer:
    return AppServer([cli, "app-server"])


def codex_models(pages: list[dict[str, Any]]) -> tuple[Model, ...]:
    """The models in `model/list`'s pages, hidden ones left out."""
    models: dict[str, Model] = {}
    for page in pages:
        for entry in page.get("data") or ():
            if not isinstance(entry, dict) or not entry.get("model") or entry.get("hidden"):
                continue
            efforts = entry.get("supportedReasoningEfforts") or ()
            models.setdefault(entry["model"], Model(
                id=entry["model"],
                name=entry.get("displayName") or entry["model"],
                description=entry.get("description") or "",
                efforts=tuple(e["reasoningEffort"] for e in efforts if e.get("reasoningEffort")),
                default_effort=entry.get("defaultReasoningEffort") or "",
                default=bool(entry.get("isDefault")),
            ))
    return tuple(models.values())


def codex_account(account: dict[str, Any]) -> str:
    """Who Codex is signed in as, in words: its email and plan."""
    kind = account.get("type")
    if kind == "apiKey":
        return "An OpenAI API key"
    if kind == "amazonBedrock":
        return "Amazon Bedrock"
    plan = str(account.get("planType") or "")
    how = f"ChatGPT {plan.title()}" if plan and plan != "unknown" else "ChatGPT"
    return " · ".join(part for part in (account.get("email") or "", how) if part)


# Pages of model/list, at most: a guard against a cursor that never ends.
MAX_PAGES = 20


def probe_openai(
    configured: str = "", *, run: Runner = _run, app_server: AppServerFactory = _app_server,
    now: datetime | None = None,
) -> Status:
    now = now or datetime.now()
    cli = find_cli(OPENAI, configured)
    if cli is None:
        return Status(OPENAI.key, "missing", now, message=_missing(OPENAI, configured))
    try:
        found = _version(run, cli, OPENAI)
        with app_server(cli) as server:
            server.request("initialize", {
                "clientInfo": {
                    "name": "personal-calendar", "title": "Personal Calendar", "version": "1",
                },
                "capabilities": {"experimentalApi": True},
            })
            server.notify("initialized")
            answer = server.request("account/read", {})
            account = answer.get("account")
            if not account and answer.get("requiresOpenaiAuth"):
                return Status(
                    OPENAI.key, "signed_out", now, cli=cli, version=found,
                    message=_signed_out(OPENAI),
                )
            pages, cursor = [], None
            for _ in range(MAX_PAGES):
                page = server.request("model/list", {"cursor": cursor} if cursor else {})
                pages.append(page)
                cursor = page.get("nextCursor")
                if not cursor:
                    break
    except ProbeFailed as exc:
        return Status(OPENAI.key, "failed", now, cli=cli, message=str(exc))
    except OSError as exc:
        message = f"The Codex CLI would not start: {exc}"
        return Status(OPENAI.key, "failed", now, cli=cli, message=message)
    return Status(
        OPENAI.key, "ready", now, cli=cli, version=found,
        account=codex_account(account or {}), models=codex_models(pages),
    )


# ---- both ----


def _missing(provider: Provider, configured: str) -> str:
    if configured:
        return f"No {provider.program} at {configured}."
    return f"{provider.program} is not on this computer's PATH."


def _signed_out(provider: Provider) -> str:
    return f"{provider.program} is not signed in."


# Checks a provider, given where its CLI was set to be ("" to find it).
Probe = Callable[[str, str], Status]


def probe(provider: str, configured: str = "") -> Status:
    """The provider as it stands now."""
    if provider == CLAUDE.key:
        return probe_claude(configured)
    if provider == OPENAI.key:
        return probe_openai(configured)
    raise KeyError(provider)

