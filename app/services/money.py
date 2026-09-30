"""Finances: Oscar's money, a month at a time (SPEC.md, Finances).

The database is the record. His banks' CSV exports are imported into his
accounts as transactions (sources/bank_csv.py), each sorted into a category
by his rules as it lands, or later, by hand or by Claude from Spending's
chat. A month is what was spent in each category against its budget, what
came in, and what is left; money moved between his own accounts is a
transfer, neither. Net worth is the sum of each account's latest balance,
what is owed counting against it. Bills come round by their cadence, and a
transaction near a due day whose description holds the bill's words pays
it. Goals are money to save, kept in an account or counted by hand.

Money is whole cents, in Australian dollars: out is negative.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    LIABILITY_KINDS,
    AccountKind,
    BillCadence,
    CategoryKind,
    MoneyAccount,
    MoneyBalance,
    MoneyBill,
    MoneyCategory,
    MoneyGoal,
    MoneyImport,
    MoneyRule,
    MoneyTransaction,
)
from app.services import DomainError
from app.sources.bank_csv import BankExport

# The categories a first look at Finances begins with; he adds, budgets
# and deletes them from there.
DEFAULT_CATEGORIES: dict[CategoryKind, list[str]] = {
    CategoryKind.spending: [
        "Groceries", "Eating out", "Transport", "Rent and housing", "Utilities",
        "Phone and internet", "Health", "Fitness", "Shopping", "Entertainment",
        "Subscriptions", "Travel", "Personal care", "Gifts and donations",
        "Fees and charges", "Other",
    ],
    CategoryKind.income: ["Salary", "Interest", "Refunds and other income"],
    CategoryKind.transfer: ["Transfers"],
}
TRANSFERS = "Transfers"
# A bill's payment may land a few days either side of its due day.
BILL_WINDOW_DAYS = 5
# The largest amount written by hand, to catch a slip of the keyboard.
MAX_CENTS = 100_000_000_00

ACCOUNT_WORDS = {
    AccountKind.everyday: "Everyday", AccountKind.savings: "Savings",
    AccountKind.credit_card: "Credit card", AccountKind.loan: "Loan",
    AccountKind.super: "Super", AccountKind.investment: "Investments",
    AccountKind.other: "Other",
}
CADENCE_WORDS = {
    BillCadence.weekly: "Weekly", BillCadence.fortnightly: "Fortnightly",
    BillCadence.monthly: "Monthly", BillCadence.quarterly: "Quarterly",
    BillCadence.yearly: "Yearly",
}
# What a bill costs a month, as a share of one payment.
PER_MONTH = {
    BillCadence.weekly: Decimal(52) / 12, BillCadence.fortnightly: Decimal(26) / 12,
    BillCadence.monthly: Decimal(1), BillCadence.quarterly: Decimal(1) / 3,
    BillCadence.yearly: Decimal(1) / 12,
}


# ---- money and months, in words ----


def parse_money(text: str, what: str = "An amount") -> int | None:
    """An amount written by hand ("1,200", "$45.50") as cents; "" as None."""
    text = text.strip().replace(",", "").replace("$", "").replace(" ", "")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise DomainError(f"{what} should be a number of dollars") from None
    if not value.is_finite():
        raise DomainError(f"{what} should be a number of dollars")
    result = int((value * 100).quantize(Decimal(1)))
    if abs(result) > MAX_CENTS:
        raise DomainError(f"{what} is more than this app counts")
    return result


def money(cents: int, *, whole: bool = False, sign: bool = False) -> str:
    """$1,234.56 (or $1,235 whole); -$12.50 out; +$12.50 with sign."""
    minus = cents < 0
    amount = abs(cents)
    text = f"${(amount + 50) // 100:,}" if whole else f"${amount // 100:,}.{amount % 100:02d}"
    if minus:
        return "-" + text
    return "+" + text if sign and cents > 0 else text


def month_of(day: date) -> date:
    """The month a day is in, as its first day."""
    return day.replace(day=1)


def month_end(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def parse_month(text: str) -> date:
    """"2026-09" as its first day."""
    try:
        year, month = text.split("-")
        return date(int(year), int(month), 1)
    except ValueError:
        raise DomainError(f"Not a month (YYYY-MM): {text}") from None


# ---- accounts and their balances ----


def accounts(db: Session) -> list[MoneyAccount]:
    return list(db.scalars(select(MoneyAccount).order_by(MoneyAccount.id)))


def account(db: Session, account_id: int) -> MoneyAccount:
    found = db.get(MoneyAccount, account_id)
    if found is None:
        raise DomainError("No such account")
    return found


def _free_name(db: Session, name: str) -> str:
    """The name, or the name with a number when one already has it."""
    taken = {a.name.lower() for a in accounts(db)}
    candidate, n = name, 2
    while candidate.lower() in taken:
        candidate, n = f"{name} {n}", n + 1
    return candidate


def add_account(
    db: Session, name: str, kind: AccountKind | str = AccountKind.everyday
) -> MoneyAccount:
    name = name.strip()
    if not name:
        raise DomainError("Name the account")
    if any(a.name.lower() == name.lower() for a in accounts(db)):
        raise DomainError(f"There is already an account called {name}")
    created = MoneyAccount(name=name[:80], kind=AccountKind(kind))
    db.add(created)
    db.flush()
    return created


def update_account(
    db: Session, account_id: int, *, name: str | None = None, kind: str | None = None
) -> MoneyAccount:
    found = account(db, account_id)
    if name is not None:
        name = name.strip()
        if not name:
            raise DomainError("Name the account")
        if any(a.id != found.id and a.name.lower() == name.lower() for a in accounts(db)):
            raise DomainError(f"There is already an account called {name}")
        found.name = name[:80]
    if kind is not None:
        found.kind = AccountKind(kind)
    db.flush()
    return found


def delete_account(db: Session, account_id: int) -> None:
    """The account, with its transactions, balances and imports."""
    found = account(db, account_id)
    for model in (MoneyTransaction, MoneyBalance, MoneyImport):
        for row in db.scalars(select(model).where(model.account_id == found.id)):
            db.delete(row)
    for goal in db.scalars(select(MoneyGoal).where(MoneyGoal.account_id == found.id)):
        goal.account_id = None
    db.delete(found)
    db.flush()


def set_balance(
    db: Session, account_id: int, day: date, cents: int, source: str = "hand"
) -> MoneyBalance:
    """The account's balance at the end of a day; a second that day replaces
    the first. What is owed is negative."""
    found = account(db, account_id)
    if found.kind in LIABILITY_KINDS and cents > 0:
        cents = -cents  # written as what is owed
    balance = db.scalars(
        select(MoneyBalance).where(MoneyBalance.account_id == found.id, MoneyBalance.day == day)
    ).first()
    if balance is None:
        balance = MoneyBalance(account_id=found.id, day=day, cents=cents, source=source)
        db.add(balance)
    else:
        balance.cents, balance.source = cents, source
    db.flush()
    return balance


def delete_balance(db: Session, balance_id: int) -> None:
    balance = db.get(MoneyBalance, balance_id)
    if balance is not None:
        db.delete(balance)
        db.flush()


def balances(db: Session, source: str | None = None, limit: int = 12) -> list[MoneyBalance]:
    """The latest balances (those written by hand, or imported), newest first."""
    query = select(MoneyBalance)
    if source is not None:
        query = query.where(MoneyBalance.source == source)
    return list(db.scalars(
        query.order_by(MoneyBalance.day.desc(), MoneyBalance.id.desc()).limit(limit)
    ))


def balance_on(db: Session, account_id: int, day: date) -> MoneyBalance | None:
    """The account's balance as it stood on a day: its latest by then."""
    return db.scalars(
        select(MoneyBalance).where(MoneyBalance.account_id == account_id, MoneyBalance.day <= day)
        .order_by(MoneyBalance.day.desc()).limit(1)
    ).first()


@dataclass
class NetWorth:
    day: date
    # (account, its balance or None when it has none by then)
    accounts: list[tuple[MoneyAccount, MoneyBalance | None]]

    @property
    def owned(self) -> int:
        return sum(b.cents for _, b in self.accounts if b is not None and b.cents > 0)

    @property
    def owed(self) -> int:
        return -sum(b.cents for _, b in self.accounts if b is not None and b.cents < 0)

    @property
    def total(self) -> int:
        return self.owned - self.owed

    @property
    def known(self) -> bool:
        return any(b is not None for _, b in self.accounts)


def net_worth(db: Session, day: date) -> NetWorth:
    return NetWorth(day, [(a, balance_on(db, a.id, day)) for a in accounts(db)])


def net_worth_by_month(db: Session, today: date, months: int = 12) -> list[tuple[date, NetWorth]]:
    """Net worth at the end of each of the last `months` months (today's
    for this one), newest first; months before any balance are left out."""
    rows = []
    for back in range(months):
        month = add_months(month_of(today), -back)
        worth = net_worth(db, min(month_end(month), today))
        if not worth.known:
            break
        rows.append((month, worth))
    return rows


# ---- categories and the rules that sort into them ----


def ensure_categories(db: Session) -> None:
    """The first categories, the first time Finances is opened."""
    if db.scalar(select(func.count()).select_from(MoneyCategory)):
        return
    for kind, names in DEFAULT_CATEGORIES.items():
        for name in names:
            db.add(MoneyCategory(name=name, kind=kind))
    db.flush()


def categories(db: Session, kind: CategoryKind | None = None) -> list[MoneyCategory]:
    query = select(MoneyCategory).order_by(func.lower(MoneyCategory.name))
    if kind is not None:
        query = query.where(MoneyCategory.kind == kind)
    return list(db.scalars(query))


def category(db: Session, category_id: int) -> MoneyCategory:
    found = db.get(MoneyCategory, category_id)
    if found is None:
        raise DomainError("No such category")
    return found


def category_named(db: Session, name: str) -> MoneyCategory:
    """A category by its name, in any case; or why not, naming them all."""
    wanted = name.strip().lower()
    every = categories(db)
    for found in every:
        if found.name.lower() == wanted:
            return found
    names = ", ".join(c.name for c in every)
    raise DomainError(f"No category called {name}. The categories: {names}")


def add_category(
    db: Session, name: str, kind: CategoryKind | str = CategoryKind.spending
) -> MoneyCategory:
    name = " ".join(name.split())
    if not name:
        raise DomainError("Name the category")
    if any(c.name.lower() == name.lower() for c in categories(db)):
        raise DomainError(f"There is already a category called {name}")
    created = MoneyCategory(name=name[:60], kind=CategoryKind(kind))
    db.add(created)
    db.flush()
    return created


def set_budget(db: Session, category_id: int, cents: int | None) -> MoneyCategory:
    """A spending category's budget a month; None for none."""
    found = category(db, category_id)
    if cents is not None and found.kind != CategoryKind.spending:
        raise DomainError(f"{found.name} is not spending, so it has no budget")
    if cents is not None and cents <= 0:
        raise DomainError("A budget is more than nothing")
    found.budget_cents = cents
    db.flush()
    return found


def delete_category(db: Session, category_id: int) -> None:
    """The category; its transactions are left unsorted, its rules go."""
    found = category(db, category_id)
    for rule in db.scalars(select(MoneyRule).where(MoneyRule.category_id == found.id)):
        db.delete(rule)
    for row in db.scalars(select(MoneyTransaction).where(MoneyTransaction.category_id == found.id)):
        row.category_id = None
    db.delete(found)
    db.flush()


def rules(db: Session) -> list[MoneyRule]:
    return list(db.scalars(select(MoneyRule).order_by(func.lower(MoneyRule.pattern))))


def _sorted_by(description: str, every: Iterable[MoneyRule]) -> MoneyRule | None:
    """The rule a description is sorted by: the longest pattern it holds,
    so "UBER EATS" wins over "UBER"."""
    text = description.lower()
    matching = [r for r in every if r.pattern.lower() in text]
    return max(matching, key=lambda r: len(r.pattern), default=None)


def add_rule(db: Session, pattern: str, category_id: int) -> tuple[MoneyRule, int]:
    """A rule, and the unsorted transactions it sorts at once (how many).
    A rule for words already ruled moves them to the new category."""
    pattern = " ".join(pattern.split())
    if len(pattern) < 3:
        raise DomainError("A rule needs at least three letters to look for")
    target = category(db, category_id)
    rule = db.scalars(
        select(MoneyRule).where(func.lower(MoneyRule.pattern) == pattern.lower())
    ).first()
    if rule is None:
        rule = MoneyRule(pattern=pattern[:120], category_id=target.id)
        db.add(rule)
    else:
        rule.category_id = target.id
    db.flush()
    every = rules(db)
    sorted_now = 0
    for row in db.scalars(select(MoneyTransaction).where(MoneyTransaction.category_id.is_(None))):
        best = _sorted_by(row.description, every)
        if best is not None and best.id == rule.id:
            row.category_id = target.id
            sorted_now += 1
    db.flush()
    return rule, sorted_now


def delete_rule(db: Session, rule_id: int) -> None:
    rule = db.get(MoneyRule, rule_id)
    if rule is not None:
        db.delete(rule)
        db.flush()


# ---- importing a bank's export ----


def import_export(
    db: Session, export: BankExport, account_id: int | None, filename: str = ""
) -> MoneyImport:
    """A bank's export into an account (a new one, named for the bank, when
    none is given): each transaction not already there added, and sorted by
    the rules; a Revolut top-up is a transfer. The balance the export shows
    at the end of each of its days becomes the account's balance that day."""
    if account_id is None:
        target = add_account(db, _free_name(db, export.bank_name))
    else:
        target = account(db, account_id)
    known = set(db.scalars(
        select(MoneyTransaction.fingerprint).where(MoneyTransaction.account_id == target.id)
    ))
    record = MoneyImport(
        account_id=target.id, filename=filename[:200], bank=export.bank,
        skipped=sum(export.skipped.values()),
    )
    db.add(record)
    db.flush()
    every = rules(db)
    transfers = db.scalars(
        select(MoneyCategory).where(MoneyCategory.name == TRANSFERS,
                                    MoneyCategory.kind == CategoryKind.transfer)
    ).first()
    for row in export.rows:
        if row.fingerprint in known:
            record.known += 1
            continue
        known.add(row.fingerprint)
        rule = _sorted_by(row.description, every)
        category_id = rule.category_id if rule else None
        if category_id is None and row.bank_type == "TOPUP" and transfers is not None:
            category_id = transfers.id
        db.add(MoneyTransaction(
            account_id=target.id, day=row.day, description=row.description[:500],
            cents=row.cents, bank_type=row.bank_type, category_id=category_id,
            fingerprint=row.fingerprint, import_id=record.id,
        ))
        record.added += 1
    for day, cents in export.balances.items():
        set_balance(db, target.id, day, cents, source="import")
    db.flush()
    return record


def imports(db: Session, limit: int = 10) -> list[MoneyImport]:
    return list(db.scalars(select(MoneyImport).order_by(MoneyImport.id.desc()).limit(limit)))


# ---- transactions ----


def transactions(
    db: Session,
    first: date | None = None,
    last: date | None = None,
    *,
    account_id: int | None = None,
    category_id: int | None = None,
    unsorted: bool = False,
    text: str = "",
    limit: int | None = None,
) -> list[MoneyTransaction]:
    """Transactions, newest first, narrowed by what is given."""
    query = select(MoneyTransaction)
    if first is not None:
        query = query.where(MoneyTransaction.day >= first)
    if last is not None:
        query = query.where(MoneyTransaction.day <= last)
    if account_id is not None:
        query = query.where(MoneyTransaction.account_id == account_id)
    if category_id is not None:
        query = query.where(MoneyTransaction.category_id == category_id)
    if unsorted:
        query = query.where(MoneyTransaction.category_id.is_(None))
    if text.strip():
        query = query.where(MoneyTransaction.description.icontains(text.strip(), autoescape=True))
    query = query.order_by(MoneyTransaction.day.desc(), MoneyTransaction.id.desc())
    if limit is not None:
        query = query.limit(limit)
    return list(db.scalars(query))


def set_category(db: Session, transaction_ids: Iterable[int], category_id: int | None) -> int:
    """Sort transactions into a category (None: unsorted); how many."""
    if category_id is not None:
        category(db, category_id)
    ids = list(transaction_ids)
    found = list(db.scalars(select(MoneyTransaction).where(MoneyTransaction.id.in_(ids))))
    if len(found) != len(set(ids)):
        missing = sorted(set(ids) - {t.id for t in found})
        raise DomainError(f"No transaction with id {', '.join(map(str, missing))}")
    for row in found:
        row.category_id = category_id
    db.flush()
    return len(found)


def set_note(db: Session, transaction_id: int, note: str) -> MoneyTransaction:
    row = db.get(MoneyTransaction, transaction_id)
    if row is None:
        raise DomainError("No such transaction")
    row.note = note.strip()[:500]
    db.flush()
    return row


# ---- a month ----


@dataclass
class CategoryMonth:
    category: MoneyCategory
    # Spent (out, positive) for spending; came in for income; moved for transfers.
    cents: int = 0
    count: int = 0


@dataclass
class Month:
    month: date
    spending: list[CategoryMonth] = field(default_factory=list)
    income: list[CategoryMonth] = field(default_factory=list)
    # Money moved between his accounts, in and out; both sides are there
    # when both accounts are imported.
    transfers_in: int = 0
    transfers_out: int = 0
    unsorted_out: int = 0
    unsorted_in: int = 0
    unsorted_count: int = 0
    count: int = 0

    @property
    def spent(self) -> int:
        """Everything spent: the spending categories and what is unsorted out."""
        return sum(c.cents for c in self.spending) + self.unsorted_out

    @property
    def came_in(self) -> int:
        return sum(c.cents for c in self.income) + self.unsorted_in

    @property
    def left(self) -> int:
        return self.came_in - self.spent

    @property
    def transfers(self) -> int:
        """What moved between his accounts: the larger side, so a move seen
        from both accounts counts once."""
        return max(self.transfers_in, self.transfers_out)

    @property
    def budgeted(self) -> int:
        return sum(c.category.budget_cents or 0 for c in self.spending)


def month_summary(db: Session, month: date) -> Month:
    """What the month's transactions add up to, category by category; every
    spending and income category has its row, spent in or not."""
    summary = Month(month)
    rows = {c.id: CategoryMonth(c) for c in categories(db)}
    for row in transactions(db, month, month_end(month)):
        summary.count += 1
        if row.category_id is None:
            summary.unsorted_count += 1
            if row.cents < 0:
                summary.unsorted_out -= row.cents
            else:
                summary.unsorted_in += row.cents
            continue
        entry = rows[row.category_id]
        entry.count += 1
        if entry.category.kind == CategoryKind.spending:
            entry.cents -= row.cents  # a refund takes from what was spent
        elif entry.category.kind == CategoryKind.income:
            entry.cents += row.cents
        elif row.cents > 0:
            summary.transfers_in += row.cents
        else:
            summary.transfers_out -= row.cents
    for entry in rows.values():
        if entry.category.kind == CategoryKind.spending:
            summary.spending.append(entry)
        elif entry.category.kind == CategoryKind.income:
            summary.income.append(entry)
    return summary


# ---- bills ----


def _monthly(anchor: date, month: date) -> date:
    """The anchor's day of the month in another month, or its last day."""
    return month.replace(day=min(anchor.day, calendar.monthrange(month.year, month.month)[1]))


def occurrences(bill: MoneyBill, first: date, last: date) -> list[date]:
    """The days a bill falls due between first and last, inclusive."""
    if bill.cadence in (BillCadence.weekly, BillCadence.fortnightly):
        step = 7 if bill.cadence == BillCadence.weekly else 14
        # The due day on or before first, then each after it.
        day = bill.due + timedelta(days=(first - bill.due).days // step * step)
        days = []
        while day <= last:
            if day >= first:
                days.append(day)
            day += timedelta(days=step)
        return days
    step = {BillCadence.monthly: 1, BillCadence.quarterly: 3, BillCadence.yearly: 12}[bill.cadence]
    anchor = month_of(bill.due)
    gap = (first.year - anchor.year) * 12 + first.month - anchor.month
    month = add_months(anchor, (gap // step) * step)
    days = []
    while month <= last:
        day = _monthly(bill.due, month)
        if first <= day <= last:
            days.append(day)
        month = add_months(month, step)
    return days


def payment(db: Session, bill: MoneyBill, due: date) -> MoneyTransaction | None:
    """The transaction that paid a bill's due day: money out, near it, its
    description holding the bill's words. None without words to look for."""
    if not bill.match.strip():
        return None
    window = timedelta(days=BILL_WINDOW_DAYS)
    for row in transactions(db, due - window, due + window, text=bill.match):
        if row.cents < 0:
            return row
    return None


@dataclass
class BillState:
    bill: MoneyBill
    next_due: date
    # The last due day up to today, and whether it was seen paid (None:
    # there are no words to look for, or none has fallen due yet).
    last_due: date | None
    paid: bool | None

    @property
    def per_month(self) -> int:
        return int((self.bill.cents * PER_MONTH[self.bill.cadence]).quantize(Decimal(1)))


def bill_state(db: Session, bill: MoneyBill, today: date) -> BillState:
    ahead = occurrences(bill, today, today + timedelta(days=400))
    behind = occurrences(bill, today - timedelta(days=400), today - timedelta(days=1))
    next_due = ahead[0] if ahead else bill.due
    last_due = behind[-1] if behind else None
    paid = None
    if bill.match.strip():
        if next_due == today:
            last_due = today
        if last_due is not None:
            paid = payment(db, bill, last_due) is not None
    return BillState(bill, next_due, last_due, paid)


def bills(db: Session) -> list[MoneyBill]:
    return list(db.scalars(select(MoneyBill).order_by(func.lower(MoneyBill.name))))


def bill(db: Session, bill_id: int) -> MoneyBill:
    found = db.get(MoneyBill, bill_id)
    if found is None:
        raise DomainError("No such bill")
    return found


def save_bill(
    db: Session,
    *,
    bill_id: int | None = None,
    name: str,
    cents: int | None,
    cadence: BillCadence | str,
    due: date | None,
    match: str = "",
) -> MoneyBill:
    """A bill, new or changed."""
    name = " ".join(name.split())
    if not name:
        raise DomainError("Name the bill")
    if cents is None or cents <= 0:
        raise DomainError("A bill's amount is more than nothing")
    if due is None:
        raise DomainError("Give the bill a day it is due")
    found = MoneyBill() if bill_id is None else bill(db, bill_id)
    found.name, found.cents, found.cadence = name[:80], cents, BillCadence(cadence)
    found.due, found.match = due, " ".join(match.split())[:120]
    if bill_id is None:
        db.add(found)
    db.flush()
    return found


def delete_bill(db: Session, bill_id: int) -> None:
    db.delete(bill(db, bill_id))
    db.flush()


def upcoming(db: Session, today: date, days: int = 30) -> list[tuple[date, MoneyBill]]:
    """Every bill's due days from today, over the next `days` days, in order."""
    last = today + timedelta(days=days - 1)
    due = [(day, b) for b in bills(db) for day in occurrences(b, today, last)]
    return sorted(due, key=lambda pair: (pair[0], pair[1].name.lower()))


# ---- goals ----


@dataclass
class GoalState:
    goal: MoneyGoal
    saved: int
    # Saved as of (an account's latest balance), None when counted by hand.
    as_of: date | None
    # A month's saving that reaches the target by its day; None without one,
    # or once it is reached.
    per_month: int | None

    @property
    def to_go(self) -> int:
        return max(0, self.goal.target_cents - self.saved)

    @property
    def percent(self) -> float:
        return min(100.0, round(100 * max(self.saved, 0) / self.goal.target_cents, 1))


def goal_state(db: Session, goal: MoneyGoal, today: date) -> GoalState:
    saved, as_of = goal.saved_cents, None
    if goal.account_id is not None:
        balance = balance_on(db, goal.account_id, today)
        saved, as_of = (balance.cents, balance.day) if balance else (0, None)
    per_month = None
    to_go = goal.target_cents - saved
    if goal.by is not None and to_go > 0:
        months = max(1, (goal.by.year - today.year) * 12 + goal.by.month - today.month)
        per_month = -(-to_go // months)
    return GoalState(goal, saved, as_of, per_month)


def goals(db: Session) -> list[MoneyGoal]:
    return list(db.scalars(select(MoneyGoal).order_by(MoneyGoal.id)))


def goal(db: Session, goal_id: int) -> MoneyGoal:
    found = db.get(MoneyGoal, goal_id)
    if found is None:
        raise DomainError("No such goal")
    return found


def save_goal(
    db: Session,
    *,
    goal_id: int | None = None,
    name: str,
    target_cents: int | None,
    by: date | None = None,
    account_id: int | None = None,
    saved_cents: int | None = None,
) -> MoneyGoal:
    """A goal, new or changed: kept in an account, or its saving counted by hand."""
    name = " ".join(name.split())
    if not name:
        raise DomainError("Name the goal")
    if target_cents is None or target_cents <= 0:
        raise DomainError("A goal's target is more than nothing")
    if account_id is not None:
        account(db, account_id)
    found = MoneyGoal() if goal_id is None else goal(db, goal_id)
    found.name, found.target_cents, found.by = name[:80], target_cents, by
    found.account_id = account_id
    if saved_cents is not None:
        found.saved_cents = saved_cents
    if goal_id is None:
        db.add(found)
    db.flush()
    return found


def delete_goal(db: Session, goal_id: int) -> None:
    db.delete(goal(db, goal_id))
    db.flush()
