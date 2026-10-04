"""The agent window's routes: the window and its chat as fragments, choosing
the agent, a new chat, and a message sent, the answer streamed back as it
is written."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import StreamingResponse

from app.db import DbSession
from app.models import AgentKind
from app.services import DomainError, agents
from app.services import agent_window as window_svc
from app.services.agent_chat import Run
from app.services.agents import Agent
from app.ui.agent_window_view import window_ctx
from app.ui.models import Prober
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


def get_agents() -> dict[AgentKind, Agent]:
    """Who answers in the window: Claude and Codex, or stand-ins under test."""
    return agents.AGENTS


def _window(request: Request, db: DbSession):
    ctx = {"request": request, "window": window_ctx(db)}
    return templates.TemplateResponse(request, "partials/agent_panel.html", ctx)


@router.get("/ui/agent")
def agent_window(request: Request, db: DbSession):
    return _window(request, db)


@router.get("/ui/agent/log")
def agent_log(request: Request, db: DbSession):
    """The latest chat, as the window's log draws it."""
    ctx = {"request": request, "chat": window_ctx(db)["chat"]}
    return templates.TemplateResponse(request, "partials/chat.html", ctx)


@router.post("/ui/agent/agent")
def choose_agent(
    request: Request, db: DbSession, probe: Prober, agent: Annotated[AgentKind, Form()]
):
    """Chat with `agent`: in the latest chat while nothing is said in it,
    else in a new one. One that was not here is asked again first, since
    Oscar may have just installed it or signed in."""
    if not window_svc.here(window_svc.status(db, agent)):
        window_svc.recheck(db, agent, probe)
    window_svc.choose(db, agent)
    return _window(request, db)


@router.post("/ui/agent/new")
def new_chat(request: Request, db: DbSession):
    """A fresh chat, with the agent of the one before."""
    latest = window_svc.current(db)
    window_svc.new_chat(db, latest.agent if latest is not None else window_svc.default_agent(db))
    return _window(request, db)


@router.post("/ui/agent/chat")
def send_message(
    db: DbSession,
    message: Annotated[str, Form()],
    agent: Annotated[AgentKind, Form()],
    roster: Annotated[dict[AgentKind, Agent], Depends(get_agents)],
    probe: Prober,
    conversation: Annotated[int | None, Form()] = None,
):
    """Oscar's message, saved; the agent's answer follows as newline-delimited
    JSON: {"type": "text" | "status", "text"} as it comes, then
    {"type": "done", "failed"}. The answer goes on, and is saved, if the
    page stops listening (Oscar went to another page)."""
    chat = window_svc.get(db, conversation) if conversation else window_svc.choose(db, agent)
    if not window_svc.here(window_svc.status(db, chat.agent)):
        found = window_svc.recheck(db, chat.agent, probe)
        if not window_svc.here(found):
            raise DomainError(found.message or f"{agents.LABELS[chat.agent]} is not here")
    run = window_svc.start(db, chat, message, agent=roster[chat.agent], now=datetime.now())
    return StreamingResponse(_follow(run), media_type="application/x-ndjson")


async def _follow(run: Run) -> AsyncIterator[str]:
    seen = 0
    while True:
        events, finished = await asyncio.to_thread(run.wait, seen, 1.0)
        for event in events:
            yield json.dumps(event) + "\n"
        seen += len(events)
        if finished:
            return
