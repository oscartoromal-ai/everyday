"""The CSV exports of Oscar's banks, read into rows: Revolut's and ING Australia's.

Which bank's it is follows from its header line. Only what the export
settled is read: Revolut's rows are kept when COMPLETED and in Australian
dollars, the others counted as skipped, with why. Amounts become whole
cents, out negative, a Revolut fee taken off its row's amount.

Each row gets a fingerprint, its identity within its account: its day,
amount and description, and how many identical rows came before it in the
file (two coffees on one day at the same price are two). An export covers
whole days, so the same transaction gets the same fingerprint in any
export that holds it, and importing overlapping exports adds it once.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CURRENCY = "AUD"

REVOLUT = ("type", "product", "started date", "completed date", "description",
           "amount", "fee", "currency", "state", "balance")
ING = ("date", "description", "credit", "debit", "balance")

BANK_NAMES = {"revolut": "Revolut", "ing": "ING"}


class ExportError(Exception):
    """A file that is not an export this app reads, or a row it cannot."""


@dataclass
class BankRow:
    day: date
    description: str
    cents: int
    bank_type: str = ""
    balance_cents: int | None = None
    fingerprint: str = ""


@dataclass
class BankExport:
    bank: str  # "revolut" or "ing"
    rows: list[BankRow]
    # Rows left out, by why ("pending", "in USD").
    skipped: Counter[str] = field(default_factory=Counter)
    # The account's balance at the end of each day the export shows one.
    balances: dict[date, int] = field(default_factory=dict)

    @property
    def closing(self) -> tuple[date, int] | None:
        """The balance at the end of the export's last day."""
        if not self.balances:
            return None
        last = max(self.balances)
        return last, self.balances[last]

    @property
    def bank_name(self) -> str:
        return BANK_NAMES[self.bank]


def cents(text: str) -> int:
    """"-1,234.50", "$12", "(12.50)" as whole cents; "" as 0."""
    text = text.strip().replace(",", "").replace("$", "").replace(" ", "")
    if not text:
        return 0
    negative = text.startswith("(") and text.endswith(")")
    try:
        value = Decimal(text.strip("()"))
    except InvalidOperation:
        raise ExportError(f"not an amount: {text}") from None
    value = int((value * 100).quantize(Decimal(1)))
    return -value if negative else value


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExportError("it is not text")


def _fingerprint(row: BankRow, seen: Counter[tuple]) -> str:
    key = (row.day.isoformat(), row.cents, " ".join(row.description.split()).lower())
    nth = seen[key]
    seen[key] += 1
    return hashlib.sha1("|".join(map(str, (*key, nth))).encode()).hexdigest()


def read(data: bytes) -> BankExport:
    """A bank's CSV export, as rows. Raises ExportError, saying why, for a
    file that is not one."""
    text = _decode(data)
    records = list(csv.reader(io.StringIO(text)))
    records = [r for r in records if any(cell.strip() for cell in r)]
    if not records:
        raise ExportError("the file is empty")
    header = tuple(cell.strip().lower() for cell in records[0])
    body = records[1:]
    if all(name in header for name in REVOLUT):
        export = _revolut(header, body)
    elif all(name in header for name in ING):
        export = _ing(header, body)
    else:
        first = ",".join(records[0])[:120]
        raise ExportError(
            f"it is not a Revolut or ING export: its first line is \"{first}\""
        )
    seen: Counter[tuple] = Counter()
    for row in export.rows:
        row.fingerprint = _fingerprint(row, seen)
    return export


def _cells(header: tuple[str, ...], record: list[str]) -> dict[str, str]:
    return {name: (record[i].strip() if i < len(record) else "") for i, name in enumerate(header)}


def _revolut(header: tuple[str, ...], body: list[list[str]]) -> BankExport:
    export = BankExport("revolut", [])
    # Each day's last balance, by when its row completed.
    latest: dict[date, tuple[datetime, int]] = {}
    for number, record in enumerate(body, start=2):
        cell = _cells(header, record)
        state = cell["state"].upper()
        if state != "COMPLETED":
            export.skipped[state.lower() or "not completed"] += 1
            continue
        if cell["currency"].upper() != CURRENCY:
            export.skipped[f"in {cell['currency'] or 'no currency'}"] += 1
            continue
        when = cell["completed date"] or cell["started date"]
        try:
            moment = datetime.fromisoformat(when)
        except ValueError:
            raise ExportError(f"line {number}: not a date: {when}") from None
        try:
            amount = cents(cell["amount"]) - cents(cell["fee"])
            balance = cents(cell["balance"]) if cell["balance"] else None
        except ExportError as exc:
            raise ExportError(f"line {number}: {exc}") from None
        export.rows.append(BankRow(
            day=moment.date(), description=cell["description"], cents=amount,
            bank_type=cell["type"].upper(), balance_cents=balance,
        ))
        seen = latest.get(moment.date())
        if balance is not None and (seen is None or moment >= seen[0]):
            latest[moment.date()] = (moment, balance)
    export.balances = {day: balance for day, (_, balance) in sorted(latest.items())}
    return export


def _ing(header: tuple[str, ...], body: list[list[str]]) -> BankExport:
    export = BankExport("ing", [])
    for number, record in enumerate(body, start=2):
        cell = _cells(header, record)
        try:
            day = datetime.strptime(cell["date"], "%d/%m/%Y").date()
        except ValueError:
            raise ExportError(f"line {number}: not a date: {cell['date']}") from None
        try:
            # A debit may be written negative or not; it is money out either way.
            amount = cents(cell["credit"]) - abs(cents(cell["debit"]))
            balance = cents(cell["balance"]) if cell["balance"] else None
        except ExportError as exc:
            raise ExportError(f"line {number}: {exc}") from None
        export.rows.append(BankRow(
            day=day, description=cell["description"], cents=amount, balance_cents=balance,
        ))
    # ING lists the newest first: a day's closing balance is its first row,
    # or its last in a file that runs the other way.
    dated = [r for r in export.rows if r.balance_cents is not None]
    if dated and dated[0].day >= dated[-1].day:
        dated.reverse()
    export.balances = {r.day: r.balance_cents for r in sorted(dated, key=lambda r: r.day)}
    return export
