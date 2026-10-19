"""Finances: banks' exports read and imported once, sorted by rules, a
month's figures, net worth, bills that come round and are seen paid, and
goals."""

from datetime import date
from pathlib import Path

import pytest

from app.models import AccountKind, BillCadence, CategoryKind, MoneyBill, MoneyTransaction
from app.services import DomainError
from app.services import money as money_svc
from app.sources import bank_csv
from app.sources.bank_csv import ExportError

DATA = Path(__file__).parent / "data"
# A month of each bank's export, as the bank writes it: Revolut's with a
# top-up, two coffees alike, a pending row, a row in USD and a fee; ING's
# newest first.
REVOLUT = (DATA / "revolut-2026-09.csv").read_text(encoding="utf-8")
ING = (DATA / "ing-2026-09.csv").read_text(encoding="utf-8")


def test_a_revolut_export_keeps_what_settled_in_dollars() -> None:
    export = bank_csv.read(REVOLUT.encode())
    assert export.bank == "revolut"
    assert [(r.day, r.description, r.cents) for r in export.rows] == [
        (date(2026, 9, 1), "Top-Up by *1234", 50000),
        (date(2026, 9, 3), "Woolworths Metro", -4520),
        (date(2026, 9, 3), "Coffee Club", -550),
        (date(2026, 9, 3), "Coffee Club", -550),
        (date(2026, 9, 15), "Netflix.com", -2299),
        # A fee comes off its row.
        (date(2026, 9, 20), "Payment from Oscar", 9900),
    ]
    assert export.skipped == {"pending": 1, "in USD": 1}
    assert export.closing == (date(2026, 9, 20), 51981)
    # Each day's balance is its last completed row's.
    assert export.balances == {
        date(2026, 9, 1): 50000, date(2026, 9, 3): 44380, date(2026, 9, 15): 42081,
        date(2026, 9, 20): 51981,
    }
    # Two coffees alike are two transactions.
    assert len({r.fingerprint for r in export.rows}) == len(export.rows)


def test_an_ing_export_reads_credits_and_debits_newest_first() -> None:
    export = bank_csv.read(("﻿" + ING).encode())
    assert export.bank == "ing"
    assert [r.cents for r in export.rows] == [312, -50000, 400000]
    assert export.closing == (date(2026, 9, 30), 1000312)
    assert export.balances[date(2026, 9, 29)] == 1000000
    # A debit written without its minus is money out all the same.
    unsigned = bank_csv.read(ING.replace("-500.00", "500.00").encode())
    assert unsigned.rows[1].cents == -50000


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("", "empty"),
        ("Name,Value\na,1\n", "not a Revolut or ING export"),
        ("Date,Description,Credit,Debit,Balance\n2026-09-30,x,1,,1\n", "line 2: not a date"),
        (ING.replace("3.12", "three"), "line 2: not an amount"),
    ],
)
def test_a_file_that_is_not_an_export_says_why(text: str, why: str) -> None:
    with pytest.raises(ExportError, match=why):
        bank_csv.read(text.encode())


def test_money_is_written_and_read_in_cents() -> None:
    assert money_svc.parse_money("$1,200.5") == 120050
    assert money_svc.parse_money(" ") is None
    with pytest.raises(DomainError):
        money_svc.parse_money("twelve")
    assert money_svc.money(-123456) == "-$1,234.56"
    assert money_svc.money(5) == "$0.05"
    assert money_svc.money(123450, whole=True) == "$1,235"
    assert money_svc.money(100, sign=True) == "+$1.00"


def test_an_export_imported_twice_adds_each_transaction_once(db) -> None:
    money_svc.ensure_categories(db)
    first = money_svc.import_export(db, bank_csv.read(REVOLUT.encode()), None, "sept.csv")
    assert (first.added, first.known, first.skipped) == (6, 0, 2)
    account = money_svc.accounts(db)[0]
    assert account.name == "Revolut"
    # A top-up is money moved from his own account.
    topup = money_svc.transactions(db, text="Top-Up")[0]
    assert topup.category.name == "Transfers"
    # The balance is the export's, day by day.
    assert money_svc.balance_on(db, account.id, date(2026, 9, 30)).cents == 51981
    assert money_svc.balance_on(db, account.id, date(2026, 9, 10)).cents == 44380

    again = money_svc.import_export(db, bank_csv.read(REVOLUT.encode()), account.id)
    assert (again.added, again.known) == (0, 6)
    # One more coffee that day, in a later export, is new.
    more = REVOLUT + (
        "CARD_PAYMENT,Current,2026-09-02 17:00:00,2026-09-03 09:00:02,Coffee Club,"
        "-5.50,0.00,AUD,COMPLETED,438.30\n"
    )
    third = money_svc.import_export(db, bank_csv.read(more.encode()), account.id)
    assert (third.added, third.known) == (1, 6)
    # Without an account, into its bank's: the one its last export went into.
    same = money_svc.import_export(db, bank_csv.read(more.encode()), None)
    assert (same.account_id, same.added, same.known) == (account.id, 0, 7)
    # A new one asked for is made, named apart.
    other = money_svc.import_export(db, bank_csv.read(REVOLUT.encode()), None, new_account=True)
    assert money_svc.account(db, other.account_id).name == "Revolut 2"
    assert other.added == 6


def test_rules_sort_what_is_imported_and_what_waits(db) -> None:
    money_svc.ensure_categories(db)
    eating = money_svc.category_named(db, "eating out")
    groceries = money_svc.category_named(db, "Groceries")
    money_svc.import_export(db, bank_csv.read(REVOLUT.encode()), None)
    # A new rule sorts the unsorted it matches, and says how many.
    _, sorted_now = money_svc.add_rule(db, "coffee club", eating.id)
    assert sorted_now == 2
    money_svc.add_rule(db, "Woolworths", groceries.id)
    # The longest match wins.
    metro = money_svc.add_category(db, "Convenience")
    rule, sorted_now = money_svc.add_rule(db, "Woolworths Metro", metro.id)
    assert sorted_now == 0  # already sorted: a rule only sorts the unsorted
    assert money_svc._sorted_by("WOOLWORTHS METRO 123", money_svc.rules(db)) == rule
    with pytest.raises(DomainError, match="three letters"):
        money_svc.add_rule(db, "ab", eating.id)
    with pytest.raises(DomainError, match="The categories:"):
        money_svc.category_named(db, "Snacks")


def test_a_month_adds_up_by_category(db) -> None:
    money_svc.ensure_categories(db)
    groceries = money_svc.category_named(db, "Groceries")
    money_svc.set_budget(db, groceries.id, 40000)
    money_svc.add_rule(db, "Woolworths", groceries.id)
    money_svc.import_export(db, bank_csv.read(REVOLUT.encode()), None)
    ing = money_svc.import_export(db, bank_csv.read(ING.encode()), None)
    salary = money_svc.category_named(db, "Salary")
    [pay] = money_svc.transactions(db, text="ACME")
    money_svc.set_category(db, [pay.id], salary.id)
    transfers = money_svc.category_named(db, "Transfers")
    [out] = money_svc.transactions(db, text="to Revolut", account_id=ing.account_id)
    money_svc.set_category(db, [out.id], transfers.id)

    month = money_svc.month_summary(db, date(2026, 9, 1))
    spent = {c.category.name: c.cents for c in month.spending}
    assert spent["Groceries"] == 4520 and spent["Travel"] == 0
    assert month.budgeted == 40000
    assert month.income[[c.category.name for c in month.income].index("Salary")].cents == 400000
    # Coffee x2 and Netflix unsorted out; interest and a payment unsorted in.
    assert (month.unsorted_count, month.unsorted_out, month.unsorted_in) == (5, 3399, 10212)
    assert month.spent == 4520 + 3399
    assert month.came_in == 400000 + 10212
    # The $500 top-up seen from both accounts moved $500, once.
    assert (month.transfers_in, month.transfers_out, month.transfers) == (50000, 50000, 50000)
    assert month.left == month.came_in - month.spent
    # A refund takes from what a category spent.
    db.add(MoneyTransaction(account_id=ing.account_id, day=date(2026, 9, 10), description="Refund",
                            cents=520, category_id=groceries.id, fingerprint="r"))
    db.flush()
    assert money_svc.month_summary(db, date(2026, 9, 1)).spending[
        [c.category.name for c in month.spending].index("Groceries")].cents == 4000
    with pytest.raises(DomainError, match="not spending"):
        money_svc.set_budget(db, salary.id, 100)


def test_deleting_a_category_leaves_its_transactions_unsorted(db) -> None:
    money_svc.ensure_categories(db)
    eating = money_svc.category_named(db, "Eating out")
    money_svc.import_export(db, bank_csv.read(REVOLUT.encode()), None)
    money_svc.add_rule(db, "Coffee", eating.id)
    money_svc.delete_category(db, eating.id)
    assert money_svc.rules(db) == []
    assert all(t.category_id is None for t in money_svc.transactions(db, text="Coffee"))


def test_net_worth_counts_what_is_owed_against_it(db) -> None:
    everyday = money_svc.add_account(db, "Revolut")
    card = money_svc.add_account(db, "Card", AccountKind.credit_card)
    money_svc.set_balance(db, everyday.id, date(2026, 8, 31), 100000)
    money_svc.set_balance(db, everyday.id, date(2026, 9, 29), 150000)
    # Written as what is owed, kept negative.
    money_svc.set_balance(db, card.id, date(2026, 9, 1), 20000)
    worth = money_svc.net_worth(db, date(2026, 9, 30))
    assert (worth.owned, worth.owed, worth.total) == (150000, 20000, 130000)
    by_month = money_svc.net_worth_by_month(db, date(2026, 9, 30))
    assert [(m, w.total) for m, w in by_month] == [
        (date(2026, 9, 1), 130000), (date(2026, 8, 1), 100000),
    ]


def test_bills_fall_due_by_their_cadence() -> None:
    monthly = MoneyBill(name="Rent", cents=1, cadence=BillCadence.monthly, due=date(2026, 1, 31))
    assert money_svc.occurrences(monthly, date(2026, 2, 1), date(2026, 4, 30)) == [
        date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30),
    ]
    fortnightly = MoneyBill(name="Gym", cents=1, cadence=BillCadence.fortnightly,
                            due=date(2026, 9, 10))
    assert money_svc.occurrences(fortnightly, date(2026, 8, 20), date(2026, 9, 30)) == [
        date(2026, 8, 27), date(2026, 9, 10), date(2026, 9, 24),
    ]
    quarterly = MoneyBill(name="Power", cents=1, cadence=BillCadence.quarterly,
                          due=date(2026, 11, 15))
    assert money_svc.occurrences(quarterly, date(2026, 1, 1), date(2026, 12, 31)) == [
        date(2026, 2, 15), date(2026, 5, 15), date(2026, 8, 15), date(2026, 11, 15),
    ]
    yearly = MoneyBill(name="Rego", cents=1, cadence=BillCadence.yearly, due=date(2024, 2, 29))
    assert money_svc.occurrences(yearly, date(2026, 1, 1), date(2026, 12, 31)) == [
        date(2026, 2, 28),
    ]


def test_a_bill_is_seen_paid_by_a_transaction_near_its_day(db) -> None:
    money_svc.import_export(db, bank_csv.read(REVOLUT.encode()), None)
    netflix = money_svc.save_bill(db, name="Netflix", cents=2299, cadence="monthly",
                                  due=date(2026, 8, 14), match="netflix")
    state = money_svc.bill_state(db, netflix, date(2026, 9, 20))
    assert (state.last_due, state.next_due, state.paid) == (
        date(2026, 9, 14), date(2026, 10, 14), True,
    )
    assert state.per_month == 2299
    gym = money_svc.save_bill(db, name="Gym", cents=1000, cadence="weekly",
                              due=date(2026, 9, 18), match="Fitness First")
    gym_state = money_svc.bill_state(db, gym, date(2026, 9, 20))
    assert gym_state.paid is False and gym_state.per_month == 4333
    no_words = money_svc.save_bill(db, name="Rent", cents=200000, cadence="monthly",
                                   due=date(2026, 9, 1))
    assert money_svc.bill_state(db, no_words, date(2026, 9, 20)).paid is None
    assert [(d, b.name) for d, b in money_svc.upcoming(db, date(2026, 9, 20), 14)] == [
        (date(2026, 9, 25), "Gym"), (date(2026, 10, 1), "Rent"), (date(2026, 10, 2), "Gym"),
    ]
    with pytest.raises(DomainError, match="more than nothing"):
        money_svc.save_bill(db, name="Free", cents=0, cadence="monthly", due=date(2026, 9, 1))


def test_a_goal_counts_its_accounts_balance_or_what_is_written(db) -> None:
    savings = money_svc.add_account(db, "ING Savings", AccountKind.savings)
    money_svc.set_balance(db, savings.id, date(2026, 9, 30), 300000)
    trip = money_svc.save_goal(db, name="Japan", target_cents=900000, by=date(2027, 3, 1),
                               account_id=savings.id)
    state = money_svc.goal_state(db, trip, date(2026, 9, 30))
    assert (state.saved, state.to_go, state.percent) == (300000, 600000, 33.3)
    assert state.as_of == date(2026, 9, 30)
    assert state.per_month == 100000  # six months to go
    fund = money_svc.save_goal(db, name="Buffer", target_cents=100, saved_cents=150)
    done = money_svc.goal_state(db, fund, date(2026, 9, 30))
    assert (done.to_go, done.percent, done.per_month) == (0, 100.0, None)
    # Deleting the account leaves the goal, counted by hand.
    money_svc.delete_account(db, savings.id)
    db.expire_all()
    assert money_svc.goal(db, trip.id).account_id is None


def test_categories_begin_once(db) -> None:
    money_svc.ensure_categories(db)
    money_svc.ensure_categories(db)
    names = [c.name for c in money_svc.categories(db, CategoryKind.transfer)]
    assert names == ["Transfers"]
    with pytest.raises(DomainError, match="already"):
        money_svc.add_category(db, "groceries")


async def test_get_finances_over_mcp(app_db) -> None:
    from fastmcp import Client

    from app.mcp.server import mcp

    with app_db() as db:
        money_svc.ensure_categories(db)
        money_svc.import_export(db, bank_csv.read(REVOLUT.encode()), None)
        money_svc.save_bill(db, name="Netflix", cents=2299, cadence="monthly",
                            due=date(2026, 9, 15), match="netflix")
        db.commit()
    async with Client(mcp) as client:
        result = (await client.call_tool("get_finances", {"month": "2026-09"})).data
    assert result["month"]["unsorted"]["transactions"] == 5
    assert result["accounts"][0]["name"] == "Revolut"
    assert result["bills"][0]["name"] == "Netflix"
    assert result["goals"] == []


def test_a_bill_coming_due_nudges_until_it_is_paid(db) -> None:
    from datetime import datetime

    from app.models import NudgeType
    from app.services import nudges as nudges_svc

    money_svc.save_bill(db, name="Netflix", cents=2299, cadence="monthly",
                        due=date(2026, 10, 14), match="netflix")
    now = datetime(2026, 10, 12, 9, 0)
    [nudge] = [n for n in nudges_svc.evaluate(db, now) if n.type == NudgeType.bill_due]
    assert nudge.message == "Netflix, $22.99, is due Wed 14 Oct."
    assert nudges_svc.wording(db, nudge, date(2026, 10, 14)) == "Netflix, $22.99, is due today."
    assert nudges_svc.evaluate(db, now) == []  # once per due day
    assert "Bills due: Netflix $22.99 (Wed 14 Oct)." in nudges_svc.build_morning_digest(db, now)
    # Paid, it stops asking.
    account = money_svc.add_account(db, "Revolut")
    db.add(MoneyTransaction(account_id=account.id, day=date(2026, 10, 13),
                            description="NETFLIX.COM", cents=-2299, fingerprint="n"))
    db.flush()
    assert nudges_svc.active_nudges(db) == []
    assert "Bills due" not in nudges_svc.build_morning_digest(db, now)
