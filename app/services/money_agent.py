"""Claude behind Spending's chat, through the Claude Agent SDK.

Its world is Oscar's finances, through the tools of money_tools.py, which
run here in the app's process on its database: no files, no shell, and no
setting, CLAUDE.md, skill or MCP server of the machine's. It can search the
web. Each message is its own run, stateless: the month's chat so far goes
into the prompt, and the tools carry everything else. An agent is any
callable from an AgentRequest to AgentEvents, so tests stand in a fake for
Claude.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.services import DomainError, claude_sdk
from app.services.claude_sdk import AgentEvent, resolve_cli
from app.services.llm import Choice
from app.services.money_tools import TOOLS, TOOLS_BY_NAME

SERVER = "money"
PREFIX = f"mcp__{SERVER}__"


@dataclass(frozen=True)
class AgentRequest:
    # The month the chat is about, as its first day.
    month: date
    now: datetime
    message: str
    # Sessions on the app's database, for the tools.
    factory: sessionmaker[Session]
    # The month's chat so far, oldest first: ("oscar" | "claude", text).
    transcript: list[tuple[str, str]] = field(default_factory=list)
    # The model it runs on, as chosen on Models (services/llm.py).
    choice: Choice = Choice("claude", None, None, "")


Agent = Callable[[AgentRequest], AsyncIterator[AgentEvent]]

SYSTEM_PROMPT = """\
You are Claude, the money coach inside Oscar's personal planner app. Oscar \
talks to you from the app's Spending page, one chat per month.

His money is in Australian dollars. He imports each bank's CSV export \
into the app, and each transaction lands in his accounts, sorted into a \
category by his rules, or left unsorted.

Your tools read and change his finances in the app: months, transactions, \
categories and budgets, sorting rules, accounts and balances, bills and \
subscriptions, and savings goals. Amounts are dollars, out negative. The page \
beside the chat shows the month you are in; it is drawn again when you finish, \
so what you change shows there.

How to help:
- Read before you answer: get_month for the month, find_transactions for the \
detail. Never guess a figure the tools can give you.
- Sort what is unsorted when he asks, or offer to when there is a lot. Read the \
descriptions; when the same merchant recurs, add a rule rather than sorting one \
by one, so later imports sort themselves. Money between his own accounts \
(Revolut top-ups, transfers to or from ING) is a transfer, not spending or income.
- When you are not sure what a transaction was, ask, listing it briefly; do not \
guess a category for something ambiguous.
- Bills and subscriptions: when you see a charge recur (monthly, fortnightly, \
yearly), offer to add it as a bill, with the words its description holds as its \
match, so the app sees it paid.
- Budgets and goals: suggest figures from what he actually spends, and say what \
they are based on. Set them only when he agrees.
- Deleting (a rule, a bill, a goal) only when he asks.
- Never invent facts about him or his money. When you need to know something, ask.

Answering:
- Be brief and concrete, a few short paragraphs at most: what you found or \
changed, in figures, and what to do next when that helps.
- Write a plain dash, never an em dash. The chat is a narrow column: use short \
Markdown lists when they help, and no tables or headings.
"""


def build_prompt(request: AgentRequest) -> str:
    """The run's prompt: when, which month, the month's chat so far, then his
    message."""
    lines = [
        f"Now: {request.now:%A %d %B %Y, %H:%M}.".replace(" 0", " "),
        f"The month this chat is about: {request.month:%B %Y} ({request.month:%Y-%m}).",
    ]
    if request.transcript:
        lines += ["", "Earlier in this month's chat:"]
        for role, text in request.transcript:
            lines += ["", f"{'Oscar' if role == 'oscar' else 'You'}:", text]
    lines += ["", "Oscar's new message:", "", request.message]
    return "\n".join(lines)


def run_tool(factory: sessionmaker[Session], name: str, args: dict[str, Any]) -> dict[str, Any]:
    """A tool's call, in a session of its own, as the SDK hands it back to
    Claude: its result as JSON, or why it could not, as an error Claude reads."""
    tool = TOOLS_BY_NAME[name]
    with factory() as db:
        try:
            result = tool.run(db, args)
            if tool.writes:
                db.commit()
        except (DomainError, KeyError, ValueError, TypeError) as exc:
            db.rollback()
            reason = f"Missing: {exc}" if isinstance(exc, KeyError) else str(exc)
            return {"content": [{"type": "text", "text": reason}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}


def status(tool: str, tool_input: dict[str, Any]) -> str:
    """What a tool call is doing, in words for the chat."""
    if tool == "WebSearch":
        return "Searching the web"
    found = TOOLS_BY_NAME.get(tool.removeprefix(PREFIX))
    return found.status(tool_input) if found else "Working"


async def claude_agent(request: AgentRequest) -> AsyncIterator[AgentEvent]:
    """Claude, through the Agent SDK: the answer as it is written, and a
    status for each tool call. Raises AgentFailed when the run fails."""
    from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

    def sdk_tool(spec):  # noqa: ANN001, ANN202
        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            return run_tool(request.factory, spec.name, args)

        return tool(spec.name, spec.description, spec.schema)(handler)

    server = create_sdk_mcp_server(SERVER, tools=[sdk_tool(t) for t in TOOLS])
    allowed = ["WebSearch", *(PREFIX + t.name for t in TOOLS)]
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=request.choice.model,
        effort=request.choice.effort,
        # No files are its: a folder of nothing in particular.
        cwd=tempfile.gettempdir(),
        cli_path=resolve_cli(request.choice.cli),
        tools=["WebSearch"],
        allowed_tools=allowed,
        mcp_servers={SERVER: server},
        permission_mode="dontAsk",
        # Nothing of the machine's own: no settings, CLAUDE.md, skills or MCP servers.
        setting_sources=[],
        strict_mcp_config=True,
        include_partial_messages=True,
        max_turns=40,
    )
    async for event in claude_sdk.run(build_prompt(request), options, status):
        yield event
