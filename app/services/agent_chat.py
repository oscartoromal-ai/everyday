"""A chat with Claude, as Nutrition's and Spending's are: Oscar's message is
saved, then Claude answers it on a thread of its own, so the run goes on
(and its answer is saved) even when the page that asked is closed. The page
follows a run's events as they come: the answer's words and what Claude is
doing meanwhile. One run at a time per chat (a day's, a month's).

Each chat keeps its own messages; this module runs the answer.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

from app.services import DomainError
from app.services.claude_sdk import AgentFailed

log = logging.getLogger(__name__)

# A run longer than this is cut short, its answer saved as far as it got.
RUN_TIMEOUT_S = 300
# The longest message Oscar can send.
MAX_MESSAGE = 4000


class Run:
    """One answer being written: its events, in order, for any page that
    follows it, and whether it has finished."""

    def __init__(self, key: Hashable) -> None:
        self.key = key
        self.events: list[dict[str, Any]] = []
        self.finished = False
        self._changed = threading.Condition()

    def emit(self, event: dict[str, Any]) -> None:
        with self._changed:
            self.events.append(event)
            self._changed.notify_all()

    def finish(self) -> None:
        with self._changed:
            self.finished = True
            self._changed.notify_all()

    def wait(self, seen: int, timeout: float) -> tuple[list[dict[str, Any]], bool]:
        """The events after the first `seen`, waiting up to `timeout` seconds
        for one, and whether the run has finished."""
        with self._changed:
            self._changed.wait_for(lambda: len(self.events) > seen or self.finished, timeout)
            return self.events[seen:], self.finished

    @property
    def said(self) -> str:
        """The answer's words so far."""
        return "".join(e["text"] for e in self.events if e["type"] == "text").strip()

    def pending(self) -> dict[str, str]:
        """The answer so far as a page draws it: what Claude is doing, and
        what it has said."""
        statuses = [e["text"] for e in self.events if e["type"] == "status"]
        said = "".join(e["text"] for e in self.events if e["type"] == "text")
        return {"status": statuses[-1] if statuses else "Thinking", "text": said}


class Runs:
    """The answers being written in one kind of chat, keyed by its chat."""

    def __init__(self) -> None:
        self._runs: dict[Hashable, Run] = {}
        self._lock = threading.Lock()

    def running(self, key: Hashable) -> Run | None:
        with self._lock:
            return self._runs.get(key)

    def begin(self, key: Hashable) -> Run:
        """A run for the chat; refused while its last answer is on its way."""
        run = Run(key)
        with self._lock:
            if key in self._runs:
                raise DomainError("Claude is still answering the last message")
            self._runs[key] = run
        return run

    def end(self, key: Hashable) -> None:
        with self._lock:
            self._runs.pop(key, None)


def check_message(text: str) -> str:
    text = text.strip()
    if not text:
        raise DomainError("Write a message first")
    if len(text) > MAX_MESSAGE:
        raise DomainError(f"That message is too long: {MAX_MESSAGE} characters at most")
    return text


def answer(
    runs: Runs,
    run: Run,
    drive: Callable[[Run], Awaitable[None]],
    save: Callable[[str, bool], None],
    name: str,
) -> None:
    """Claude's answer, on a thread of its own: `drive` runs Claude,
    emitting its events on the run; then `save(text, failed)` keeps what it
    said (why it failed, when it did)."""
    threading.Thread(
        target=_work, args=(runs, run, drive, save), name=name, daemon=True
    ).start()


def _work(
    runs: Runs,
    run: Run,
    drive: Callable[[Run], Awaitable[None]],
    save: Callable[[str, bool], None],
) -> None:
    text, failed = "", False
    try:
        # Its own event loop: asyncio.run's default on Windows (Proactor)
        # can run the CLI as a subprocess whatever loop served the request.
        asyncio.run(_timed(drive(run)))
        text = run.said
    except AgentFailed as exc:
        failed, text = True, _with_reason(run, str(exc))
    except TimeoutError:
        failed, text = True, _with_reason(run, "Claude took too long, so the answer was cut short.")
    except Exception as exc:
        log.exception("Chat run failed")
        failed, text = True, _with_reason(run, f"Something went wrong: {exc}")
    try:
        save(text, failed)
    except Exception:
        log.exception("Could not save Claude's answer")
    finally:
        run.emit({"type": "done", "failed": failed})
        runs.end(run.key)
        run.finish()


async def _timed(work: Awaitable[None]) -> None:
    async with asyncio.timeout(RUN_TIMEOUT_S):
        await work


def _with_reason(run: Run, reason: str) -> str:
    said = run.said
    return f"{said}\n\n{reason}" if said else reason
