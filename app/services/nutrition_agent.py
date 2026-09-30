"""Claude behind Nutrition's chat, through the Claude Agent SDK.

The SDK runs Claude Code (the CLI already logged in on this machine, so no
API key) as an agent whose world is the nutrition folder: it reads the plan
and the day's log, writes what Oscar ate into that log, and answers him. A
hook keeps every file tool inside the folder, and no MCP server, setting
or CLAUDE.md of the machine's reaches it, so it sees only what it is given.

Each message is its own run, stateless: the day's chat so far and Oscar's
profile go into the prompt, and the files carry everything else. An agent
is any callable from an AgentRequest to AgentEvents, so tests stand in a
fake for Claude.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from app.config import get_settings


class AgentFailed(Exception):
    """Claude could not run, or stopped with an error; the message says why."""


@dataclass(frozen=True)
class AgentEvent:
    # "text": words of the answer, as they come; "status": what Claude is
    # doing meanwhile ("Reading the plan").
    kind: Literal["text", "status"]
    text: str


@dataclass(frozen=True)
class AgentRequest:
    day: date
    now: datetime
    message: str
    folder: Path
    profile: dict[str, Any] = field(default_factory=dict)
    # The day's chat so far, oldest first: ("oscar" | "claude", text).
    transcript: list[tuple[str, str]] = field(default_factory=list)
    # A turn Oscar does not see: fixing a file that did not parse.
    repair: bool = False


Agent = Callable[[AgentRequest], AsyncIterator[AgentEvent]]

SYSTEM_PROMPT = """\
You are Claude, the nutrition coach inside Oscar's personal planner app. \
Oscar talks to you from the app's Nutrition page, one chat per day.

Your working folder holds his nutrition, as Markdown files:
- plan.md: his nutrition plan. His context, rules, what a plate looks like, \
and his daily targets in its YAML front matter.
- meals/*.md: simple recipes he likes.
- log/YYYY-MM-DD.md: one file per day, what he ate or plans to eat.

On every turn, read plan.md and the day's log (when it exists) before you answer.

When Oscar says what he ate, or you agree on what he will eat, write it into the \
day's log straight away, creating the file if it does not exist. The app reads \
the log's front matter to draw the day, so it must follow this format exactly:

---
date: 2026-09-30
meals:
  - name: Breakfast
    status: eaten
    items:
      - food: Soy milk
        amount: 250 ml
        assumed: true
        kcal: 130
        protein_g: 8
        fat_g: 4.5
        sat_fat_g: 0.5
        carbs_g: 10
        fibre_g: 1
---

## Notes

Short notes on the day, one sentence per line.

## Next

What to eat next, and what to buy, one sentence per line.

Rules for the log:
- date is the day the file is for. meals are in the order they were eaten.
- status is "eaten" or "planned". A meal you recommended stays "planned" until \
he says he ate it; then set it to "eaten" and correct its items to what he had.
- Every item has all six nutrients as plain numbers: kcal, protein_g, fat_g, \
sat_fat_g, carbs_g, fibre_g. sat_fat_g is part of fat_g, never more.
- Estimate from typical values for the foods as sold in Australia. When he gives \
no amount, assume a typical one, write it in amount, and set assumed: true. \
When he corrects an amount, update the item and drop assumed.
- Never write totals: the app sums the items.
- Write the front matter in the block style shown. Put double quotes around a \
food or amount that holds a colon or a # sign.
- No other fields in the front matter. Keep the body to the Notes and Next \
sections, short, one sentence per line.
- Change plan.md only when Oscar asks, or when a target clearly has to move \
(his weight or goal changed); keep its targets front matter in the same shape.

Answering in the chat:
- Be brief and concrete, a few short paragraphs at most: what you logged (and any \
amount you assumed), where the day stands against his targets in a sentence (the \
page beside the chat already shows every total), and what to eat next when that helps.
- When he needs to buy something, give a short shopping list and simple steps. \
Follow the plan's constraints on cooking and on anything else it names.
- Never invent facts about him. When you need to know something, ask.
- Write a plain dash, never an em dash. The chat is a narrow column: use short \
Markdown lists when they help, and no tables or headings.
"""

REPAIR_PROMPT = """\
The day's log, {path}, does not follow the format, so the app cannot read it: \
{problem}
Fix the file so it follows the format exactly, keeping everything it records. \
Oscar does not see this turn: say nothing to him, only fix the file."""


def build_prompt(request: AgentRequest) -> str:
    """The run's prompt: when and which day, Oscar's profile, the day's chat
    so far, then his message (or the repair asked for)."""
    log = f"log/{request.day.isoformat()}.md"
    day_words = request.day.strftime("%A %d %B %Y").replace(" 0", " ")
    lines = [
        f"Now: {request.now:%A %d %B %Y, %H:%M}.".replace(" 0", " "),
        f"The day this chat is about: {day_words} (its log is {log}).",
        "",
        "His profile, from the app's Health > Me page:",
        json.dumps(request.profile, default=str, ensure_ascii=False, indent=1),
    ]
    if request.repair:
        lines += ["", REPAIR_PROMPT.format(path=log, problem=request.message)]
        return "\n".join(lines)
    if request.transcript:
        lines += ["", "Earlier in this day's chat:"]
        for role, text in request.transcript:
            lines += ["", f"{'Oscar' if role == 'oscar' else 'You'}:", text]
    lines += ["", "Oscar's new message:", "", request.message]
    return "\n".join(lines)


def resolve_cli(configured: str = "") -> Path:
    """The Claude Code executable to run. Windows will only run a native
    claude.exe for the SDK (a .cmd would go through cmd.exe), so npm's
    claude.cmd shim leads to the claude.exe npm installed beside it."""
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise AgentFailed(f"No Claude Code at {configured} ([nutrition].claude_cli)")
        return path
    found = shutil.which("claude")
    if found is None:
        raise AgentFailed(
            "Claude Code is not installed here: install it, or set [nutrition].claude_cli"
        )
    path = Path(found)
    if path.suffix.lower() in (".cmd", ".bat"):
        package = path.parent / "node_modules" / "@anthropic-ai" / "claude-code"
        native = package / "bin" / "claude.exe"
        if not native.is_file():
            raise AgentFailed(
                f"Claude Code at {path} is a script the SDK cannot run: "
                "set [nutrition].claude_cli to a claude.exe"
            )
        return native
    return path


# The file tools, and where in their input each names a path.
FILE_TOOLS = {"Read": "file_path", "Write": "file_path", "Edit": "file_path",
              "Glob": "path", "Grep": "path"}
TOOLS = [*FILE_TOOLS, "WebSearch"]


def outside(folder: Path, tool: str, tool_input: dict[str, Any]) -> str | None:
    """Why a file tool's call reaches outside the folder, or None when it
    stays in it (a relative path is taken from the folder)."""
    key = FILE_TOOLS.get(tool)
    if key is None:
        return None
    root = folder.resolve()
    targets = [tool_input.get(key) or "."]
    if tool == "Glob":
        targets.append(tool_input.get("pattern") or ".")
    for target in targets:
        path = Path(target)
        resolved = (path if path.is_absolute() else root / path).resolve()
        if resolved != root and root not in resolved.parents:
            return f"{target} is outside the nutrition folder; only its files are yours"
    return None


def _status(tool: str, tool_input: dict[str, Any], request: AgentRequest) -> str:
    """What a tool call is doing, in words for the chat."""
    if tool == "WebSearch":
        return "Searching the web"
    if tool in ("Glob", "Grep"):
        return "Looking through the files"
    name = Path(str(tool_input.get("file_path", ""))).as_posix()
    if name.endswith("plan.md"):
        what = "the plan"
    elif name.endswith(f"log/{request.day.isoformat()}.md"):
        what = "the day's log"
    elif "/log/" in name or name.startswith("log/"):
        what = "an earlier day's log"
    elif "/meals/" in name or name.startswith("meals/"):
        what = "a recipe"
    else:
        what = "a file"
    verb = {"Read": "Reading", "Write": "Writing", "Edit": "Updating"}[tool]
    return f"{verb} {what}"


async def claude_agent(request: AgentRequest) -> AsyncIterator[AgentEvent]:
    """Claude, through the Agent SDK: the answer as it is written, and a
    status for each tool call. Raises AgentFailed when the run fails."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKError,
        HookMatcher,
        ResultMessage,
        StreamEvent,
        TextBlock,
        ToolUseBlock,
        query,
    )

    settings = get_settings()
    folder = request.folder

    async def confine(hook_input, tool_use_id, context):  # noqa: ANN001, ANN202, ARG001
        reason = outside(folder, hook_input["tool_name"], hook_input["tool_input"])
        if reason is None:
            return {}
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=settings.nutrition.model,
        cwd=folder,
        cli_path=resolve_cli(settings.nutrition.claude_cli),
        tools=TOOLS,
        allowed_tools=TOOLS,
        permission_mode="dontAsk",
        hooks={"PreToolUse": [HookMatcher(matcher="|".join(FILE_TOOLS), hooks=[confine])]},
        # Nothing of the machine's own: no settings, CLAUDE.md, skills or MCP servers.
        setting_sources=[],
        strict_mcp_config=True,
        include_partial_messages=True,
        max_turns=40,
    )

    said = False  # any words yet, so a later block starts a new paragraph
    streamed = False  # the current text block came as deltas
    try:
        async for message in query(prompt=build_prompt(request), options=options):
            if isinstance(message, StreamEvent):
                event = message.event
                kind = event.get("type")
                if kind == "content_block_start" and event["content_block"]["type"] == "text":
                    streamed = False
                    if said:
                        yield AgentEvent("text", "\n\n")
                elif kind == "content_block_delta" and event["delta"]["type"] == "text_delta":
                    streamed = said = True
                    yield AgentEvent("text", event["delta"]["text"])
            elif isinstance(message, AssistantMessage):
                # Each block arrives whole after its deltas; one that did not
                # stream is said whole.
                for block in message.content:
                    if isinstance(block, TextBlock) and not streamed and block.text:
                        if said:
                            yield AgentEvent("text", "\n\n")
                        said = True
                        yield AgentEvent("text", block.text)
                    elif isinstance(block, ToolUseBlock):
                        yield AgentEvent("status", _status(block.name, block.input, request))
                streamed = False
            elif isinstance(message, ResultMessage) and message.is_error:
                detail = "; ".join(message.errors or []) or message.result or message.subtype
                raise AgentFailed(f"Claude stopped with an error: {detail}")
    except ClaudeSDKError as exc:
        raise AgentFailed(f"Claude could not run: {exc}") from exc
