"""Finances' routes: Spending (a month's page, its figures and transactions
as fragments, and its chat with Claude, the answer streamed back as it is
written), Accounts, Bills and Goals, each of those one sheet drawn again
after each change."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.db import DbSession
from app.models import AccountKind, BillCadence, CategoryKind, MoneyTransaction
from app.services import DomainError
from app.services import money as money_svc
from app.services import money_chat as chat_svc
from app.services.agent_chat import Run
from app.services.money_agent import Agent, claude_agent
from app.sources import bank_csv
from app.ui.money_view import (
    accounts_ctx,
    bills_ctx,
    chat_ctx,
    goals_ctx,
    spending_page_ctx,
    totals_ctx,
    transaction_row,
    transactions_ctx,
)
from app.ui.views import templates

router = APIRouter(include_in_schema=False)

# The largest export read, well past a year of a busy account.
MAX_EXPORT_BYTES = 5_000_000


def get_agent() -> Agent:
    """Who answers in the chat: Claude, or a stand-in under test."""
    return claude_agent


def _month(text: str) -> date:
    return money_svc.parse_month(text)


def _day(text: str, what: str) -> date | None:
    if not text.strip():
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise DomainError(f"{what} should be a date") from None


def _render(request: Request, template: str, ctx: dict[str, Any], **headers: str) -> Response:
    response = templates.TemplateResponse(request, template, {"request": request, **ctx})
    response.headers.update(headers)
    return response


# ---- Spending ----


@router.get("/spending")
def spending_this_month(request: Request, db: DbSession):
    return _spending(request, db, money_svc.month_of(date.today()))


@router.get("/spending/{month}")
def spending_month(request: Request, db: DbSession, month: str):
    chosen = _month(month)
    if chosen == money_svc.month_of(date.today()):
        return RedirectResponse("/spending", status_code=303)
    return _spending(request, db, chosen)


def _spending(request: Request, db: Session, month: date) -> Response:
    money_svc.ensure_categories(db)
    db.commit()
    today = date.today()
    ctx = spending_page_ctx(db, month, today)
    return _render(request, "spending.html", {"active": "spending", "today": today, **ctx})


def _sheet_ctx(db: Session, month: date) -> dict[str, Any]:
    today = date.today()
    return {
        "month": month, "today": today, "has_accounts": bool(money_svc.accounts(db)),
        "totals": totals_ctx(db, month, today),
        "transactions": transactions_ctx(db, month, today),
    }


@router.get("/ui/money/{month}/sheet")
def spending_sheet(request: Request, db: DbSession, month: str):
    return _render(request, "partials/money_sheet.html", _sheet_ctx(db, _month(month)))


@router.get("/ui/money/{month}/totals")
def spending_totals(request: Request, db: DbSession, month: str):
    chosen = _month(month)
    return _render(request, "partials/money_totals.html",
                   {"month": chosen, "totals": totals_ctx(db, chosen, date.today())})


@router.post("/ui/money/{month}/budgets/{category_id}")
def set_budget(
    request: Request, db: DbSession, month: str, category_id: int,
    budget: Annotated[str, Form()] = "",
):
    money_svc.set_budget(db, category_id, money_svc.parse_money(budget, "A budget"))
    db.commit()
    return spending_totals(request, db, month)


@router.post("/ui/money/{month}/categories")
def add_category(
    request: Request, db: DbSession, month: str,
    name: Annotated[str, Form()], kind: Annotated[str, Form()] = "spending",
):
    money_svc.add_category(db, name, CategoryKind(kind))
    db.commit()
    # Every transaction's menu offers it too.
    return Response(status_code=204, headers={"HX-Trigger": "money:changed"})


@router.post("/ui/money/{month}/categories/{category_id}/delete")
def delete_category(db: DbSession, month: str, category_id: int):  # noqa: ARG001
    money_svc.delete_category(db, category_id)
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": "money:changed"})


@router.post("/ui/money/transactions/{transaction_id}/category")
def sort_transaction(
    request: Request, db: DbSession, transaction_id: int,
    category_id: Annotated[str, Form()] = "",
):
    money_svc.set_category(db, [transaction_id], int(category_id) if category_id else None)
    db.commit()
    row = db.get(MoneyTransaction, transaction_id)
    db.refresh(row)
    ctx = {
        "row": transaction_row(row, len(money_svc.accounts(db)) > 1),
        "categories": transactions_ctx(db, money_svc.month_of(row.day), date.today())["categories"],
    }
    # The month's figures follow.
    return _render(
        request, "partials/money_transaction.html", ctx, **{"HX-Trigger": "money:sorted"}
    )


@router.get("/ui/money/{month}/chat")
def spending_chat(request: Request, db: DbSession, month: str):
    chosen = _month(month)
    chat = chat_ctx(db, chosen)
    response = _render(request, "partials/chat.html", {"chat": chat})
    # A page that opened mid-answer asks after it (#chat-pending); once it
    # has landed, the month is drawn again too, as Claude left it.
    if request.headers.get("HX-Trigger") == "chat-pending" and chat["pending"] is None:
        response.headers["HX-Trigger"] = "money:answered"
    return response


@router.post("/ui/money/{month}/chat")
def send_message(
    db: DbSession, month: str, message: Annotated[str, Form()],
    agent: Annotated[Agent, Depends(get_agent)],
):
    """Oscar's message, saved; Claude's answer follows as newline-delimited
    JSON: {"type": "text" | "status", "text"} as it comes, then
    {"type": "done", "failed"}. The answer goes on, and is saved, if the
    page stops listening."""
    run = chat_svc.start(db, _month(month), message, agent=agent, now=datetime.now())
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


# ---- Accounts ----


@router.get("/accounts")
def accounts_page(request: Request, db: DbSession):
    money_svc.ensure_categories(db)
    db.commit()
    today = date.today()
    return _render(request, "accounts.html",
                   {"active": "accounts", "today": today, **accounts_ctx(db, today)})


def _accounts(request: Request, db: Session, **extra: Any) -> Response:
    ctx = {**accounts_ctx(db, date.today()), "imported": None, "import_error": "", **extra}
    return _render(request, "partials/money_accounts.html", ctx)


@router.post("/ui/money/import")
def import_export(
    request: Request, db: DbSession,
    export: Annotated[UploadFile, File()], account_id: Annotated[str, Form()] = "",
):
    # A plain def, run on a worker thread: its writes may wait on SQLite's
    # lock, and the server's loop must not wait with them.
    data = export.file.read(MAX_EXPORT_BYTES + 1)
    filename = export.filename or ""
    if len(data) > MAX_EXPORT_BYTES:
        return _accounts(request, db, import_error=f"{filename} is too big for a bank's export.")
    try:
        parsed = bank_csv.read(data)
    except bank_csv.ExportError as exc:
        return _accounts(request, db, import_error=f"{filename} cannot be imported: {exc}.")
    # Into the account chosen, a new one ("new"), or its bank's (none chosen).
    record = money_svc.import_export(
        db, parsed, int(account_id) if account_id.isdigit() else None, filename,
        new_account=account_id == "new",
    )
    db.commit()
    return _accounts(request, db, imported=_import_words(db, parsed, record))


def _import_words(db: Session, parsed: bank_csv.BankExport, record: Any) -> dict[str, Any]:
    """What an import did, for the line under the form."""
    account = money_svc.account(db, record.account_id)
    parts = [f"{record.added} added to {account.name}"]
    if record.known:
        parts.append(f"{record.known} already here")
    if parsed.skipped:
        why = ", ".join(f"{n} {reason}" for reason, n in parsed.skipped.most_common())
        parts.append(f"{sum(parsed.skipped.values())} left out ({why})")
    closing = ""
    if parsed.closing is not None:
        day, cents = parsed.closing
        closing = f"Balance {money_svc.money(cents)} on {day.day} {day:%b}."
    first = min((r.day for r in parsed.rows), default=None)
    months = money_svc.month_of(first) if first else None
    return {"text": f"{parsed.bank_name}: " + "; ".join(parts) + ".", "closing": closing,
            "month": months}


@router.post("/ui/money/accounts")
def add_account(
    request: Request, db: DbSession,
    name: Annotated[str, Form()], kind: Annotated[str, Form()] = "everyday",
):
    money_svc.add_account(db, name, AccountKind(kind))
    db.commit()
    return _accounts(request, db)


@router.post("/ui/money/accounts/{account_id}")
def update_account(
    request: Request, db: DbSession, account_id: int,
    name: Annotated[str, Form()], kind: Annotated[str, Form()],
):
    money_svc.update_account(db, account_id, name=name, kind=kind)
    db.commit()
    return _accounts(request, db)


@router.post("/ui/money/accounts/{account_id}/delete")
def delete_account(request: Request, db: DbSession, account_id: int):
    money_svc.delete_account(db, account_id)
    db.commit()
    return _accounts(request, db)


@router.post("/ui/money/balances")
def log_balance(
    request: Request, db: DbSession,
    account_id: Annotated[int, Form()], amount: Annotated[str, Form()],
    day: Annotated[str, Form()] = "",
):
    cents = money_svc.parse_money(amount, "A balance")
    if cents is None:
        raise DomainError("Write the balance in dollars")
    money_svc.set_balance(db, account_id, _day(day, "The day") or date.today(), cents)
    db.commit()
    return _accounts(request, db)


@router.post("/ui/money/balances/{balance_id}/delete")
def delete_balance(request: Request, db: DbSession, balance_id: int):
    money_svc.delete_balance(db, balance_id)
    db.commit()
    return _accounts(request, db)


@router.post("/ui/money/rules")
def add_rule(
    request: Request, db: DbSession,
    pattern: Annotated[str, Form()], category_id: Annotated[int, Form()],
):
    _, count = money_svc.add_rule(db, pattern, category_id)
    db.commit()
    return _accounts(request, db, rule_sorted=count)


@router.post("/ui/money/rules/{rule_id}/delete")
def delete_rule(request: Request, db: DbSession, rule_id: int):
    money_svc.delete_rule(db, rule_id)
    db.commit()
    return _accounts(request, db)


# ---- Bills ----


@router.get("/bills")
def bills_page(request: Request, db: DbSession):
    today = date.today()
    return _render(request, "bills.html", {"active": "bills", **bills_ctx(db, today)})


def _bills(request: Request, db: Session) -> Response:
    return _render(request, "partials/money_bills.html", bills_ctx(db, date.today()))


def _save_bill(db: Session, bill_id: int | None, name: str, amount: str, cadence: str,
               due: str, match: str) -> None:
    money_svc.save_bill(
        db, bill_id=bill_id, name=name, cents=money_svc.parse_money(amount, "The amount"),
        cadence=BillCadence(cadence), due=_day(due, "The due day"), match=match,
    )
    db.commit()


@router.post("/ui/money/bills")
def add_bill(
    request: Request, db: DbSession,
    name: Annotated[str, Form()], amount: Annotated[str, Form()],
    cadence: Annotated[str, Form()] = "monthly", due: Annotated[str, Form()] = "",
    match: Annotated[str, Form()] = "",
):
    _save_bill(db, None, name, amount, cadence, due, match)
    return _bills(request, db)


@router.post("/ui/money/bills/{bill_id}")
def save_bill(
    request: Request, db: DbSession, bill_id: int,
    name: Annotated[str, Form()], amount: Annotated[str, Form()],
    cadence: Annotated[str, Form()] = "monthly", due: Annotated[str, Form()] = "",
    match: Annotated[str, Form()] = "",
):
    _save_bill(db, bill_id, name, amount, cadence, due, match)
    return _bills(request, db)


@router.post("/ui/money/bills/{bill_id}/delete")
def delete_bill(request: Request, db: DbSession, bill_id: int):
    money_svc.delete_bill(db, bill_id)
    db.commit()
    return _bills(request, db)


# ---- Goals ----


@router.get("/goals")
def goals_page(request: Request, db: DbSession):
    today = date.today()
    return _render(request, "goals.html", {"active": "goals", **goals_ctx(db, today)})


def _goals(request: Request, db: Session) -> Response:
    return _render(request, "partials/money_goals.html", goals_ctx(db, date.today()))


def _save_goal(db: Session, goal_id: int | None, name: str, target: str, by: str,
               account_id: str, saved: str) -> None:
    money_svc.save_goal(
        db, goal_id=goal_id, name=name, target_cents=money_svc.parse_money(target, "The target"),
        by=_day(by, "The day"), account_id=int(account_id) if account_id else None,
        saved_cents=money_svc.parse_money(saved, "What is saved") if not account_id else None,
    )
    db.commit()


@router.post("/ui/money/goals")
def add_goal(
    request: Request, db: DbSession,
    name: Annotated[str, Form()], target: Annotated[str, Form()],
    by: Annotated[str, Form()] = "", account_id: Annotated[str, Form()] = "",
    saved: Annotated[str, Form()] = "",
):
    _save_goal(db, None, name, target, by, account_id, saved)
    return _goals(request, db)


@router.post("/ui/money/goals/{goal_id}")
def save_goal(
    request: Request, db: DbSession, goal_id: int,
    name: Annotated[str, Form()], target: Annotated[str, Form()],
    by: Annotated[str, Form()] = "", account_id: Annotated[str, Form()] = "",
    saved: Annotated[str, Form()] = "",
):
    _save_goal(db, goal_id, name, target, by, account_id, saved)
    return _goals(request, db)


@router.post("/ui/money/goals/{goal_id}/delete")
def delete_goal(request: Request, db: DbSession, goal_id: int):
    money_svc.delete_goal(db, goal_id)
    db.commit()
    return _goals(request, db)
