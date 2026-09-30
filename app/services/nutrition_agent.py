"""Claude behind Nutrition's chat, through the Claude Agent SDK.

The SDK runs Claude Code (the CLI already logged in on this machine, so no
API key) as an agent whose world is the nutrition folder: it reads the plan
and the day's log, writes what Oscar ate into that log, and answers him. A
hook keeps every file tool inside the folder, and no MCP server, setting
or CLAUDE.md of the machine's reaches it, so it sees only what it is given.

Each message is its own run, stateless: the day's chat so far, Oscar's
profile and what his Garmin measured go into the prompt, and the files
carry everything else. An agent
is any callable from an AgentRequest to AgentEvents, so tests stand in a
fake for Claude.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services import claude_sdk
from app.services.claude_sdk import AgentEvent, AgentFailed, resolve_cli

__all__ = ["AgentEvent", "AgentFailed", "AgentRequest", "claude_agent", "resolve_cli"]


@dataclass(frozen=True)
class AgentRequest:
    day: date
    now: datetime
    message: str
    folder: Path
    profile: dict[str, Any] = field(default_factory=dict)
    # The day's chat so far, oldest first: ("oscar" | "claude", text).
    transcript: list[tuple[str, str]] = field(default_factory=list)
    # What his Garmin measured the day before and on the day (garmin.report).
    garmin: list[dict[str, Any]] = field(default_factory=list)
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
- When the prompt carries what his Garmin watch measured, use it: energy burned \
(total_kcal, active_kcal) and activities tell you how hard the day was, and sleep \
how he recovers. Today's figures are so far, not the whole day. Do not change the \
plan's targets for one day; say what a big day means for what to eat next, when it matters.
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
    if request.garmin:
        lines += [
            "",
            "What his Garmin watch measured (sleep is the night that ended that morning; "
            "the chat's day is so far when it is today):",
            json.dumps(request.garmin, default=str, ensure_ascii=False, indent=1),
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
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

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
        cli_path=resolve_cli(settings.claude.cli),
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

    def status(tool: str, tool_input: dict[str, Any]) -> str:
        return _status(tool, tool_input, request)

    async for event in claude_sdk.run(build_prompt(request), options, status):
        yield event
