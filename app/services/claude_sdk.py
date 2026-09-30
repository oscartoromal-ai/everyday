"""Claude through the Claude Agent SDK, for the app's chats (Nutrition,
Spending).

The SDK runs Claude Code, the CLI already logged in on this machine, so no
API key is needed. Each chat gives it its own system prompt, tools and
world; this module runs it and turns what it does into AgentEvents: the
answer's words as they are written, and a status line for each tool call.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


class AgentFailed(Exception):
    """Claude could not run, or stopped with an error; the message says why."""


@dataclass(frozen=True)
class AgentEvent:
    # "text": words of the answer, as they come; "status": what Claude is
    # doing meanwhile ("Reading the plan").
    kind: Literal["text", "status"]
    text: str


def resolve_cli(configured: str = "") -> Path:
    """The Claude Code executable to run. Windows will only run a native
    claude.exe for the SDK (a .cmd would go through cmd.exe), so npm's
    claude.cmd shim leads to the claude.exe npm installed beside it."""
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise AgentFailed(f"No Claude Code at {configured} ([claude].cli)")
        return path
    found = shutil.which("claude")
    if found is None:
        raise AgentFailed("Claude Code is not installed here: install it, or set [claude].cli")
    path = Path(found)
    if path.suffix.lower() in (".cmd", ".bat"):
        package = path.parent / "node_modules" / "@anthropic-ai" / "claude-code"
        native = package / "bin" / "claude.exe"
        if not native.is_file():
            raise AgentFailed(
                f"Claude Code at {path} is a script the SDK cannot run: "
                "set [claude].cli to a claude.exe"
            )
        return native
    return path


async def run(
    prompt: str, options: Any, status: Callable[[str, dict[str, Any]], str]
) -> AsyncIterator[AgentEvent]:
    """Claude on `prompt` with the SDK's `options`: the answer as it is
    written, and `status(tool, input)` for each tool call. Raises
    AgentFailed when the run fails."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeSDKError,
        ResultMessage,
        StreamEvent,
        TextBlock,
        ToolUseBlock,
        query,
    )

    said = False  # any words yet, so a later block starts a new paragraph
    streamed = False  # the current text block came as deltas
    try:
        async for message in query(prompt=prompt, options=options):
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
                        yield AgentEvent("status", status(block.name, block.input))
                streamed = False
            elif isinstance(message, ResultMessage) and message.is_error:
                detail = "; ".join(message.errors or []) or message.result or message.subtype
                raise AgentFailed(f"Claude stopped with an error: {detail}")
    except ClaudeSDKError as exc:
        raise AgentFailed(f"Claude could not run: {exc}") from exc
