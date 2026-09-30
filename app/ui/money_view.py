"""Finances as its pages draw it: Spending (a month against its budgets,
its transactions, and its chat with Claude), Accounts (net worth, balances,
imports and rules), Bills and Goals."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.dates import short_date
from app.models import LIABILITY_KINDS, CategoryKind, MoneyAccount, MoneyTransaction
from app.services import money as money_svc
from app.services import money_chat as chat_svc
from app.services.money import ACCOUNT_WORDS, CADENCE_WORDS, money
from app.ui import chat_view

CATEGORY_KIND_WORDS = {
    CategoryKind.spending: "Spending", CategoryKind.income: "Income",
    CategoryKind.transfer: "Transfer",
}


def _day_words(day: date, today: date) -> str:
    """Today, Yesterday, Mon 28 Sep: short_date with its first letter up."""
    words = short_date(day, today)
    return words[:1].upper() + words[1:]


def dollars_input(cents: int | None) -> str:
    """An amount as written in a field: 1200, or 45.50."""
    if cents is None:
        return ""
    whole, part = divmod(abs(cents), 100)
    text = f"{whole}" if not part else f"{whole}.{part:02d}"
    return f"-{text}" if cents < 0 else text


def _meter(part: int, whole: int) -> float:
    return min(100.0, round(100 * max(part, 0) / whole, 1)) if whole > 0 else 0.0


# ---- Spending ----


def transaction_row(row: MoneyTransaction, many_accounts: bool) -> dict[str, Any]:
    return {
        "id": row.id, "description": row.description, "note": row.note,
        "account": row.account.name if many_accounts else "",
        "category_id": row.category_id,
        "amount": money(row.cents, sign=True), "in": row.cents > 0,
    }


def totals_ctx(db: Session, month: date, today: date) -> dict[str, Any]:
    """The month's figures: what was spent against the budgets, what came
    in, what is left, and what is not sorted yet."""
    summary = money_svc.month_summary(db, month)
    budgets = []
    for entry in summary.spending:
        budget = entry.category.budget_cents
        budgets.append({
            "id": entry.category.id, "name": entry.category.name, "count": entry.count,
            "spent": money(entry.cents, whole=True) if entry.count else "",
            "spent_cents": entry.cents, "budget": dollars_input(budget),
            "meter": _meter(entry.cents, budget) if budget else None,
            "over": budget is not None and entry.cents > budget,
            "left": money(budget - entry.cents, whole=True)
            if budget and entry.cents <= budget else "",
        })
    # What was spent in first, most first; then the rest by name.
    budgets.sort(key=lambda b: (not b["count"], -b["spent_cents"] if b["count"] else 0,
                                b["name"].lower()))
    budgeted = summary.budgeted
    return {
        "month": month,
        "so_far": month == money_svc.month_of(today),
        "count": summary.count,
        "spent": money(summary.spent, whole=True),
        "budgeted": money(budgeted, whole=True) if budgeted else "",
        "spent_meter": _meter(summary.spent, budgeted) if budgeted else None,
        "over_budget": bool(budgeted) and summary.spent > budgeted,
        "came_in": money(summary.came_in, whole=True),
        "left": money(summary.left, whole=True),
        "left_cents": summary.left,
        "transfers": money(summary.transfers, whole=True) if summary.transfers else "",
        "unsorted_count": summary.unsorted_count,
        "unsorted_out": money(summary.unsorted_out, whole=True),
        "unsorted_in": money(summary.unsorted_in, whole=True),
        "budgets": budgets,
        "income": [
            {"name": c.category.name, "amount": money(c.cents, whole=True)}
            for c in sorted(summary.income, key=lambda c: -c.cents) if c.count
        ],
        "kinds": CATEGORY_KIND_WORDS,
    }


def transactions_ctx(db: Session, month: date, today: date) -> dict[str, Any]:
    """The month's transactions, a group a day, newest first."""
    many = len(money_svc.accounts(db)) > 1
    by_day: dict[date, list[MoneyTransaction]] = defaultdict(list)
    for row in money_svc.transactions(db, month, money_svc.month_end(month)):
        by_day[row.day].append(row)
    days = []
    for day, rows in by_day.items():
        days.append({
            "day": day, "label": _day_words(day, today),
            "total": money(sum(r.cents for r in rows), sign=True),
            "rows": [transaction_row(r, many) for r in rows],
        })
    return {
        "days": days,
        "categories": [
            {"kind": CATEGORY_KIND_WORDS[kind],
             "options": [(c.id, c.name) for c in money_svc.categories(db, kind)]}
            for kind in CategoryKind
        ],
    }


def chat_ctx(db: Session, month: date) -> dict[str, Any]:
    ctx = chat_view.chat_ctx(chat_svc.messages(db, month), chat_svc.running(month))
    return {
        **ctx,
        "url": f"/ui/money/{month:%Y-%m}/chat",
        "empty": 'Nothing said yet. Try: "Sort what is unsorted this month."',
    }


def spending_page_ctx(db: Session, month: date, today: date) -> dict[str, Any]:
    this_month = money_svc.month_of(today)
    return {
        "month": month,
        "is_current": month == this_month,
        "prev_month": money_svc.add_months(month, -1),
        "next_month": money_svc.add_months(month, 1),
        "has_accounts": bool(money_svc.accounts(db)),
        "totals": totals_ctx(db, month, today),
        "transactions": transactions_ctx(db, month, today),
        "chat": chat_ctx(db, month),
    }


# ---- Accounts ----


def _balance_words(cents: int, kind_owes: bool) -> str:
    if kind_owes and cents <= 0:
        return f"{money(-cents)} owed"
    return money(cents)


def accounts_ctx(db: Session, today: date) -> dict[str, Any]:
    worth = money_svc.net_worth(db, today)
    rows = []
    for account, balance in worth.accounts:
        owes = account.kind in LIABILITY_KINDS
        rows.append({
            "id": account.id, "name": account.name, "kind": account.kind.value,
            "owes": owes,
            "balance": _balance_words(balance.cents, owes) if balance else "",
            "as_of": short_date(balance.day, today) if balance else "",
        })
    trend = money_svc.net_worth_by_month(db, today)
    months = []
    for index, (month, value) in enumerate(trend):
        before = trend[index + 1][1].total if index + 1 < len(trend) else None
        months.append({
            "label": month.strftime("%b %Y"), "total": money(value.total, whole=True),
            "change": money(value.total - before, whole=True, sign=True)
            if before is not None else "",
        })
    change = ""
    if len(trend) > 1:
        change = money(worth.total - trend[1][1].total, whole=True, sign=True)
    # Those written by hand: an import's are its account's, day by day.
    balances = []
    for balance in money_svc.balances(db, source="hand"):
        account = money_svc.account(db, balance.account_id)
        balances.append({
            "id": balance.id, "account": account.name,
            "label": _day_words(balance.day, today),
            "amount": _balance_words(balance.cents, account.kind in LIABILITY_KINDS),
        })
    return {
        "today": today,
        "known": worth.known,
        "net_worth": money(worth.total, whole=True),
        "owned": money(worth.owned, whole=True),
        "owed": money(worth.owed, whole=True),
        "change": change,
        "last_month": trend[1][0].strftime("%B") if len(trend) > 1 else "",
        "accounts": rows,
        "account_words": {k.value: w for k, w in ACCOUNT_WORDS.items()},
        "balances": balances,
        "months": months,
        "imports": [
            {"when": f"{_day_words(i.imported_at.date(), today)}"
                     f" {i.imported_at:%H:%M}",
             "account": _name(db, i.account_id), "file": i.filename, "added": i.added,
             "known": i.known}
            for i in money_svc.imports(db, 5)
        ],
        "rules": [
            {"id": r.id, "pattern": r.pattern, "category": r.category.name}
            for r in money_svc.rules(db)
        ],
        "categories": [
            {"kind": CATEGORY_KIND_WORDS[kind],
             "options": [(c.id, c.name) for c in money_svc.categories(db, kind)]}
            for kind in CategoryKind
        ],
    }


def _name(db: Session, account_id: int) -> str:
    found = db.get(MoneyAccount, account_id)
    return found.name if found else ""


# ---- Bills ----


def bills_ctx(db: Session, today: date) -> dict[str, Any]:
    states = [money_svc.bill_state(db, b, today) for b in money_svc.bills(db)]
    rows = []
    for s in states:
        status = None
        if s.paid is True:
            status = ("ok", f"Paid {short_date(s.last_due, today)}")
        elif s.paid is False:
            waiting = s.last_due + timedelta(days=money_svc.BILL_WINDOW_DAYS) >= today
            status = ("warn", "Not seen yet") if waiting else (
                "err", f"Not seen for {short_date(s.last_due, today)}")
        rows.append({
            "id": s.bill.id, "name": s.bill.name, "amount": dollars_input(s.bill.cents),
            "cadence": s.bill.cadence.value, "next_due": s.next_due,
            "match": s.bill.match, "status": status,
            "per_month": money(s.per_month) if s.bill.cadence.value != "monthly" else "",
        })
    coming = money_svc.upcoming(db, today, 30)
    return {
        "today": today,
        "bills": rows,
        "cadences": {k.value: w for k, w in CADENCE_WORDS.items()},
        "a_month": money(sum(s.per_month for s in states), whole=True),
        "coming": [
            {"label": _day_words(day, today), "name": b.name,
             "amount": money(b.cents)}
            for day, b in coming
        ],
        "coming_total": money(sum(b.cents for _, b in coming), whole=True),
    }


# ---- Goals ----


def goals_ctx(db: Session, today: date) -> dict[str, Any]:
    rows = []
    for goal in money_svc.goals(db):
        s = money_svc.goal_state(db, goal, today)
        rows.append({
            "id": goal.id, "name": goal.name, "target": dollars_input(goal.target_cents),
            "by": goal.by, "account_id": goal.account_id,
            "saved_input": dollars_input(goal.saved_cents),
            "saved": money(s.saved, whole=True), "of": money(goal.target_cents, whole=True),
            "to_go": money(s.to_go, whole=True) if s.to_go else "",
            "percent": s.percent,
            "reached": s.to_go == 0,
            "as_of": short_date(s.as_of, today) if s.as_of else "",
            "per_month": money(s.per_month, whole=True) if s.per_month else "",
            "by_words": f"{goal.by:%b %Y}" if goal.by else "",
            "late": goal.by is not None and goal.by < today and s.to_go > 0,
        })
    return {
        "today": today,
        "goals": rows,
        "accounts": [(a.id, a.name) for a in money_svc.accounts(db)],
    }
