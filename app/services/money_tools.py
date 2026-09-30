"""What Claude can do with Oscar's finances, from Spending's chat: read a
month, find transactions, sort them, make rules, set budgets, and keep his
accounts' balances, bills and goals.

Each tool is a plain function over a database session, taking and giving
JSON: amounts in dollars (a number, out negative), days as YYYY-MM-DD,
months as YYYY-MM. money_agent.py hands them to Claude; the app's MCP
server reads through the same ones.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models import AccountKind, BillCadence, CategoryKind, MoneyTransaction
from app.services import DomainError
from app.services import money as money_svc

MAX_ROWS = 300


def dollars(cents: int) -> float:
    return round(cents / 100, 2)


def to_cents(value: Any, what: str = "amount") -> int:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise DomainError(f"The {what} should be a number of dollars") from None
    if not amount.is_finite():
        raise DomainError(f"The {what} should be a number of dollars")
    return int((amount * 100).quantize(Decimal(1)))


def _day(value: Any, what: str = "day") -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise DomainError(f"The {what} should be a date, YYYY-MM-DD: {value}") from None


def _account(db: Session, name: str) -> Any:
    for found in money_svc.accounts(db):
        if found.name.lower() == str(name).strip().lower():
            return found
    names = ", ".join(a.name for a in money_svc.accounts(db)) or "none yet"
    raise DomainError(f"No account called {name}. The accounts: {names}")


def transaction_out(row: MoneyTransaction) -> dict[str, Any]:
    return {
        "id": row.id, "day": row.day.isoformat(), "account": row.account.name,
        "description": row.description, "amount": dollars(row.cents),
        "category": row.category.name if row.category else None,
        **({"note": row.note} if row.note else {}),
    }


# ---- reading ----


def get_month(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    month = money_svc.parse_month(args["month"])
    summary = money_svc.month_summary(db, month)
    return {
        "month": month.strftime("%Y-%m"),
        "spent": dollars(summary.spent), "came_in": dollars(summary.came_in),
        "left_over": dollars(summary.left),
        "moved_between_accounts": dollars(summary.transfers),
        "budgeted": dollars(summary.budgeted),
        "spending": [
            {"category": c.category.name, "spent": dollars(c.cents), "transactions": c.count,
             "budget": dollars(c.category.budget_cents) if c.category.budget_cents else None}
            for c in summary.spending if c.count or c.category.budget_cents
        ],
        "income": [
            {"category": c.category.name, "came_in": dollars(c.cents), "transactions": c.count}
            for c in summary.income if c.count
        ],
        "unsorted": {"transactions": summary.unsorted_count, "out": dollars(summary.unsorted_out),
                     "in": dollars(summary.unsorted_in)},
        "categories": [
            {"name": c.name, "kind": c.kind.value} for c in money_svc.categories(db)
        ],
    }


def find_transactions(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    first = last = None
    if args.get("month"):
        first = money_svc.parse_month(args["month"])
        last = money_svc.month_end(first)
    if args.get("start"):
        first = _day(args["start"], "start")
    if args.get("end"):
        last = _day(args["end"], "end")
    category_id = None
    if args.get("category"):
        category_id = money_svc.category_named(db, args["category"]).id
    account_id = _account(db, args["account"]).id if args.get("account") else None
    limit = min(int(args.get("limit") or 100), MAX_ROWS)
    rows = money_svc.transactions(
        db, first, last, account_id=account_id, category_id=category_id,
        unsorted=bool(args.get("unsorted")), text=str(args.get("text") or ""), limit=limit + 1,
    )
    return {
        "transactions": [transaction_out(r) for r in rows[:limit]],
        "more": len(rows) > limit,
    }


def get_accounts(db: Session, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    today = date.today()
    worth = money_svc.net_worth(db, today)
    return {
        "net_worth": dollars(worth.total), "owned": dollars(worth.owned),
        "owed": dollars(worth.owed),
        "accounts": [
            {"name": a.name, "kind": a.kind.value,
             "balance": dollars(b.cents) if b else None, "as_of": b.day.isoformat() if b else None}
            for a, b in worth.accounts
        ],
        "net_worth_by_month": [
            {"month": m.strftime("%Y-%m"), "net_worth": dollars(w.total)}
            for m, w in money_svc.net_worth_by_month(db, today)
        ],
        "latest_imports": [
            {"account": money_svc.account(db, i.account_id).name, "bank": i.bank,
             "imported_at": i.imported_at.isoformat(timespec="minutes"), "added": i.added}
            for i in money_svc.imports(db, 5)
        ],
        "rules": [{"words": r.pattern, "category": r.category.name} for r in money_svc.rules(db)],
    }


def get_bills(db: Session, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    today = date.today()
    states = [money_svc.bill_state(db, b, today) for b in money_svc.bills(db)]
    return {
        "a_month": dollars(sum(s.per_month for s in states)),
        "bills": [
            {"id": s.bill.id, "name": s.bill.name, "amount": dollars(s.bill.cents),
             "cadence": s.bill.cadence.value, "next_due": s.next_due.isoformat(),
             "match": s.bill.match,
             "last_due": s.last_due.isoformat() if s.last_due else None, "last_paid": s.paid}
            for s in states
        ],
    }


def get_goals(db: Session, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    today = date.today()
    goals = []
    for g in money_svc.goals(db):
        s = money_svc.goal_state(db, g, today)
        goals.append({
            "id": g.id, "name": g.name, "target": dollars(g.target_cents),
            "by": g.by.isoformat() if g.by else None,
            "account": g.account.name if g.account else None,
            "saved": dollars(s.saved), "to_go": dollars(s.to_go),
            "a_month_to_get_there": dollars(s.per_month) if s.per_month else None,
        })
    return {"goals": goals}


# ---- changing ----


def sort_transactions(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("category") or "").strip()
    category_id = money_svc.category_named(db, name).id if name else None
    count = money_svc.set_category(db, [int(i) for i in args["transaction_ids"]], category_id)
    return {"sorted": count, "category": name or None}


def add_rule(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    category = money_svc.category_named(db, args["category"])
    rule, count = money_svc.add_rule(db, args["words"], category.id)
    return {"rule": rule.pattern, "category": category.name, "sorted_now": count}


def delete_rule(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    wanted = str(args["words"]).strip().lower()
    for rule in money_svc.rules(db):
        if rule.pattern.lower() == wanted:
            money_svc.delete_rule(db, rule.id)
            return {"deleted": rule.pattern}
    raise DomainError(f"No rule for {args['words']}")


def add_category(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    created = money_svc.add_category(db, args["name"], CategoryKind(args.get("kind") or "spending"))
    return {"added": created.name, "kind": created.kind.value}


def set_budget(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    category = money_svc.category_named(db, args["category"])
    amount = args.get("amount")
    cents = to_cents(amount, "budget") if amount not in (None, "", 0) else None
    money_svc.set_budget(db, category.id, cents)
    return {"category": category.name, "budget": dollars(cents) if cents else None}


def set_balance(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    found = _account(db, args["account"])
    day = _day(args.get("day") or date.today().isoformat())
    balance = money_svc.set_balance(db, found.id, day, to_cents(args["amount"], "balance"))
    return {"account": found.name, "day": day.isoformat(), "balance": dollars(balance.cents)}


def add_account(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    created = money_svc.add_account(db, args["name"], AccountKind(args.get("kind") or "everyday"))
    return {"added": created.name, "kind": created.kind.value}


def save_bill(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    saved = money_svc.save_bill(
        db, bill_id=args.get("id"), name=args["name"], cents=to_cents(args["amount"]),
        cadence=BillCadence(args.get("cadence") or "monthly"), due=_day(args["due"], "due day"),
        match=str(args.get("match") or ""),
    )
    return {"saved": saved.name, "id": saved.id}


def delete_bill(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    found = money_svc.bill(db, int(args["id"]))
    money_svc.delete_bill(db, found.id)
    return {"deleted": found.name}


def save_goal(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    account_id = _account(db, args["account"]).id if args.get("account") else None
    saved = args.get("saved")
    kept = money_svc.save_goal(
        db, goal_id=args.get("id"), name=args["name"], target_cents=to_cents(args["target"]),
        by=_day(args["by"], "by") if args.get("by") else None, account_id=account_id,
        saved_cents=to_cents(saved, "saved") if saved not in (None, "") else None,
    )
    return {"saved": kept.name, "id": kept.id}


def delete_goal(db: Session, args: dict[str, Any]) -> dict[str, Any]:
    found = money_svc.goal(db, int(args["id"]))
    money_svc.delete_goal(db, found.id)
    return {"deleted": found.name}


# ---- the tools as Claude sees them ----

_MONTH = {"type": "string", "description": "A month, YYYY-MM"}
_DAY = {"type": "string", "description": "A day, YYYY-MM-DD"}
_KINDS = [k.value for k in CategoryKind]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[[Session, dict[str, Any]], dict[str, Any]]
    # What the chat says while it runs.
    status: Callable[[dict[str, Any]], str]
    writes: bool = False


def _object(required: list[str], **properties: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


def _month_words(args: dict[str, Any]) -> str:
    try:
        return money_svc.parse_month(str(args.get("month"))).strftime("%B's")
    except DomainError:
        return "a month's"


def _count(args: dict[str, Any]) -> str:
    n = len(args.get("transaction_ids") or [])
    return f"{n} transaction{'s' if n != 1 else ''}"


TOOLS = [
    Tool("get_month", "A month's money: spent by category against each budget, what came in, "
         "what is left, what is unsorted, and every category's name and kind.",
         _object(["month"], month=_MONTH), get_month,
         lambda a: f"Reading {_month_words(a)} spending"),
    Tool("find_transactions", "Transactions, newest first, narrowed by a month or start and end "
         "days, words in the description (any case), a category, an account, or unsorted only. "
         f"At most {MAX_ROWS}; `more` says when there are more.",
         _object([], month=_MONTH, start=_DAY, end=_DAY,
                 text={"type": "string", "description": "Words the description holds"},
                 category={"type": "string"}, account={"type": "string"},
                 unsorted={"type": "boolean"}, limit={"type": "integer", "minimum": 1}),
         find_transactions, lambda a: "Looking through transactions"),
    Tool("sort_transactions", "Put transactions (by id) in a category by its name; an empty "
         "category leaves them unsorted.",
         _object(["transaction_ids", "category"],
                 transaction_ids={"type": "array", "items": {"type": "integer"}},
                 category={"type": "string"}),
         sort_transactions, lambda a: f"Sorting {_count(a)}", writes=True),
    Tool("add_rule", "A rule: every transaction whose description holds these words (any case) "
         "goes in the category, from now on as it is imported, and the unsorted ones now. "
         "The longest words that match win.",
         _object(["words", "category"], words={"type": "string"}, category={"type": "string"}),
         add_rule, lambda a: "Adding a rule", writes=True),
    Tool("delete_rule", "Delete the rule for these words.",
         _object(["words"], words={"type": "string"}),
         delete_rule, lambda a: "Deleting a rule", writes=True),
    Tool("add_category", "A new category: spending, income, or transfer (money moved between "
         "his own accounts, neither spent nor earned).",
         _object(["name", "kind"], name={"type": "string"},
                 kind={"type": "string", "enum": _KINDS}),
         add_category, lambda a: "Adding a category", writes=True),
    Tool("set_budget", "A spending category's budget a month, in dollars; null for none.",
         _object(["category", "amount"], category={"type": "string"},
                 amount={"type": ["number", "null"]}),
         set_budget, lambda a: "Setting a budget", writes=True),
    Tool("get_accounts", "His accounts and their latest balances, net worth (and by month), "
         "the latest imports, and the sorting rules.",
         _object([]), get_accounts, lambda a: "Reading the accounts"),
    Tool("set_balance", "An account's balance at the end of a day (default today), in dollars; "
         "what a card or loan owes can be given as a positive amount.",
         _object(["account", "amount"], account={"type": "string"}, amount={"type": "number"},
                 day=_DAY),
         set_balance, lambda a: "Writing a balance", writes=True),
    Tool("add_account", "A new account: everyday, savings, credit_card, loan, super, "
         "investment or other.",
         _object(["name", "kind"], name={"type": "string"},
                 kind={"type": "string", "enum": [k.value for k in AccountKind]}),
         add_account, lambda a: "Adding an account", writes=True),
    Tool("get_bills", "His bills and subscriptions: each one's amount, cadence, next due day, "
         "the words its payment's description holds, and whether its last due day was seen paid "
         "(null without words); with what they come to a month.",
         _object([]), get_bills, lambda a: "Reading the bills"),
    Tool("save_bill", "Add a bill (no id) or change one (its id). `due` is any day it falls due; "
         "`match` the words its payment's description holds, so the app sees it paid.",
         _object(["name", "amount", "cadence", "due"], id={"type": "integer"},
                 name={"type": "string"}, amount={"type": "number"},
                 cadence={"type": "string", "enum": [c.value for c in BillCadence]},
                 due=_DAY, match={"type": "string"}),
         save_bill, lambda a: "Saving a bill", writes=True),
    Tool("delete_bill", "Delete a bill by its id.", _object(["id"], id={"type": "integer"}),
         delete_bill, lambda a: "Deleting a bill", writes=True),
    Tool("get_goals", "His savings goals: target, by when, what is saved (an account's balance, "
         "or counted by hand), what is to go, and a month's saving that gets there.",
         _object([]), get_goals, lambda a: "Reading the goals"),
    Tool("save_goal", "Add a goal (no id) or change one (its id): kept in an account (its "
         "balance is the progress), or `saved` counted by hand.",
         _object(["name", "target"], id={"type": "integer"}, name={"type": "string"},
                 target={"type": "number"}, by=_DAY, account={"type": "string"},
                 saved={"type": "number"}),
         save_goal, lambda a: "Saving a goal", writes=True),
    Tool("delete_goal", "Delete a goal by its id.", _object(["id"], id={"type": "integer"}),
         delete_goal, lambda a: "Deleting a goal", writes=True),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
