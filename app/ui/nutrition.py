"""Nutrition's routes: a day's page, its log and chat as fragments, and
sending Claude a message, its answer streamed back as it is written."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from app.config import get_settings
from app.db import DbSession
from app.services import health as health_svc
from app.services import nutrition_chat as chat_svc
from app.services.nutrition_agent import Agent, claude_agent
from app.ui.nutrition_view import chat_ctx, log_ctx, nutrition_page_ctx
from app.ui.views import templates

router = APIRouter(include_in_schema=False)


def get_agent() -> Agent:
    """Who answers in the chat: Claude, or a stand-in under test."""
    return claude_agent


@router.get("/nutrition")
def nutrition_today(request: Request, db: DbSession):
    return _page(request, db, date.today())


@router.get("/nutrition/{day}")
def nutrition_day(request: Request, db: DbSession, day: date):
    if day == date.today():
        return RedirectResponse("/nutrition", status_code=303)
    return _page(request, db, day)


def _page(request: Request, db: DbSession, day: date):
    today = date.today()
    ctx = nutrition_page_ctx(db, get_settings().nutrition_dir, day, today)
    return templates.TemplateResponse(
        request, "nutrition.html",
        {"request": request, "active": "nutrition", "today": today, **ctx},
    )


@router.get("/ui/nutrition/{day}/log")
def nutrition_log(request: Request, day: date):
    ctx = {"request": request, "day": day, "nutrition": log_ctx(get_settings().nutrition_dir, day)}
    return templates.TemplateResponse(request, "partials/nutrition_log.html", ctx)


@router.get("/ui/nutrition/{day}/chat")
def nutrition_chat(request: Request, db: DbSession, day: date):
    chat = chat_ctx(db, day)
    ctx = {"request": request, "day": day, "today": date.today(), "chat": chat}
    response = templates.TemplateResponse(request, "partials/nutrition_chat.html", ctx)
    # A page that opened mid-answer asks after it (#chat-pending); once it
    # has landed, the log is drawn again too, as Claude left it.
    if request.headers.get("HX-Trigger") == "chat-pending" and chat["pending"] is None:
        response.headers["HX-Trigger"] = "nutrition:answered"
    return response


@router.post("/ui/nutrition/{day}/chat")
def send_message(
    db: DbSession,
    day: date,
    message: Annotated[str, Form()],
    agent: Annotated[Agent, Depends(get_agent)],
):
    """Oscar's message, saved; Claude's answer follows as newline-delimited
    JSON: {"type": "text" | "status", "text"} as it comes, then
    {"type": "done", "failed"}. The answer goes on, and is saved, if the
    page stops listening."""
    profile = health_svc.context(db, date.today())
    run = chat_svc.start(db, day, message, agent=agent, profile=profile, now=datetime.now())
    return StreamingResponse(_follow(run), media_type="application/x-ndjson")


async def _follow(run: chat_svc.Run) -> AsyncIterator[str]:
    seen = 0
    while True:
        events, finished = await asyncio.to_thread(run.wait, seen, 1.0)
        for event in events:
            yield json.dumps(event) + "\n"
        seen += len(events)
        if finished:
            return
