"""Where Oscar stays, day by day (Oscar's call on 2026-09-27: he moves
around, and does not always have a bed sorted).

A day's stay is its items, in order: each a name (place and accommodation
to begin with, any other his to name), a value, and whether it is sorted.
A new stay starts with the items the last one had. A stay is written day by
day, not as a range: Today's stay pane carries one on to the days after it
(fill) or takes the last one again (same_as_before), and Calendar's sheet
fills one down its days. Stays were written in the day's notes ("/stay")
until 2026-10-20, when Oscar took them out into a pane of their own: they
are fields, so the database's alone (Files first), with no file.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import StayItem
from app.services import DomainError

# What a first stay lists, with none written before it.
FIRST_ITEMS = ("place", "accommodation")
# Items that are a checkbox, whether they are sorted, as Oscar's Excel had
# its AC column (Oscar's call on 2026-10-03); the rest are their words.
CHECK_ITEMS = ("accommodation",)
# How far a stay is carried on at once (fill): a year.
MOST_DAYS = 366
# The values an item had before, offered as it is written.
VALUES_OFFERED = 8


def clean_name(name: Any) -> str:
    """An item's name as kept: its words, single-spaced."""
    if not isinstance(name, str):
        raise DomainError("A stay item's name must be text")
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > 80:
        raise DomainError(f"Not a stay item: {name!r}")
    return cleaned


def is_check(name: str) -> bool:
    """The item is a checkbox, sorted or not (its words too, if any)."""
    return name.lower() in CHECK_ITEMS


def items_on(db: Session, day: date) -> list[StayItem]:
    """The day's stay, its items in order; none, no stay."""
    return list(
        db.scalars(
            select(StayItem).where(StayItem.day == day).order_by(StayItem.position, StayItem.id)
        )
    )


def between(db: Session, first: date, last: date) -> dict[date, list[StayItem]]:
    """Each day's stay from `first` to `last`, those with one."""
    out: dict[date, list[StayItem]] = {}
    for item in db.scalars(
        select(StayItem)
        .where(StayItem.day >= first, StayItem.day <= last)
        .order_by(StayItem.day, StayItem.position, StayItem.id)
    ):
        out.setdefault(item.day, []).append(item)
    return out


def as_dicts(items: Iterable[StayItem]) -> list[dict[str, Any]]:
    """Items as read out: name, value and sorted or not."""
    return [{"name": i.name, "value": i.value, "done": i.done} for i in items]


def is_empty(items: Iterable[StayItem]) -> bool:
    """Nothing said: no item with a value, none sorted."""
    return not any(i.value or i.done for i in items)


def last_day_before(db: Session, day: date) -> date | None:
    """The last day before `day` with a stay."""
    return db.scalar(select(func.max(StayItem.day)).where(StayItem.day < day))


def starting_items(db: Session, day: date) -> list[str]:
    """The items a stay written on `day` starts with: those the last one
    before it lists, or place and accommodation."""
    before = last_day_before(db, day)
    if before is not None:
        return [i.name for i in items_on(db, before)]
    return list(FIRST_ITEMS)


def values_used(db: Session, names: Iterable[str]) -> dict[str, list[str]]:
    """Each item's values written before, the latest first, so a place is
    written as it was the last time."""
    out: dict[str, list[str]] = {}
    for name in names:
        rows = db.execute(
            select(StayItem.value, func.max(StayItem.day).label("last"))
            .where(func.lower(StayItem.name) == name.lower(), StayItem.value != "")
            .group_by(StayItem.value)
            .order_by(func.max(StayItem.day).desc())
            .limit(VALUES_OFFERED)
        )
        out[name] = [value for value, _last in rows]
    return out


def _find(items: list[StayItem], name: str) -> StayItem | None:
    return next((i for i in items if i.name.lower() == name.lower()), None)


def _append(db: Session, items: list[StayItem], day: date, name: str) -> StayItem:
    """A new item at the end of the day's stay."""
    item = StayItem(day=day, position=max((i.position for i in items), default=-1) + 1, name=name)
    db.add(item)
    return item


def _started(db: Session, day: date) -> list[StayItem]:
    """A stay for the day, with the items the last one had."""
    items = [
        StayItem(day=day, position=n, name=name) for n, name in enumerate(starting_items(db, day))
    ]
    db.add_all(items)
    return items


def set_item(
    db: Session, day: date, name: str, *, value: str | None = None, done: bool | None = None
) -> list[StayItem]:
    """An item of the day's stay set: its value, or whether it is sorted
    (None leaves either as it was). A day with no stay gets one, with the
    items the last stay had; an item the stay does not list joins it at its
    end. Answers the day's stay."""
    name = clean_name(name)
    if value is not None:
        value = " ".join(value.split())
    items = items_on(db, day)
    if not items:
        if not value and not done:
            return []  # nothing to write
        items = _started(db, day)
    item = _find(items, name) or _append(db, items, day, name)
    if value is not None:
        item.value = value
    if done is not None:
        item.done = done
    db.flush()
    return items_on(db, day)


def add_item(db: Session, day: date, name: str) -> list[StayItem]:
    """A new item for the day's stay, at its end (a day with none gets the
    items the last stay had first). Answers the day's stay."""
    name = clean_name(name)
    items = items_on(db, day) or _started(db, day)
    if _find(items, name) is None:
        _append(db, items, day, name)
    db.flush()
    return items_on(db, day)


def remove_item(db: Session, day: date, name: str) -> list[StayItem]:
    """An item gone from the day's stay (its last gone, the day has none).
    Answers the day's stay."""
    item = _find(items_on(db, day), clean_name(name))
    if item is not None:
        db.delete(item)
        db.flush()
    return items_on(db, day)


def _put_day(db: Session, day: date, items: list[dict[str, Any]]) -> None:
    """The day's stay made `items` (name, value, done), item for item; none,
    no stay."""
    db.execute(delete(StayItem).where(StayItem.day == day))
    db.add_all(
        StayItem(day=day, position=n, name=i["name"], value=i["value"], done=i["done"])
        for n, i in enumerate(items)
    )


def same_as_before(db: Session, day: date) -> list[StayItem]:
    """The day's stay made the last one before it. Answers the day's stay."""
    before = last_day_before(db, day)
    if before is None:
        raise DomainError("No stay before this day to take again")
    _put_day(db, day, as_dicts(items_on(db, before)))
    db.flush()
    return items_on(db, day)


def fill(db: Session, day: date, until: date) -> dict[date, list[dict[str, Any]]]:
    """The day's stay carried on to every day after it up to `until`, each
    made the same, item for item. Answers what each of those days had
    before (put takes them back)."""
    source = as_dicts(items_on(db, day))
    if not source:
        raise DomainError("This day has no stay to carry on")
    if until <= day:
        raise DomainError("A stay is carried on to a later day")
    if (until - day).days > MOST_DAYS:
        raise DomainError(f"A stay is carried on {MOST_DAYS} days at most")
    days = [day + timedelta(days=i) for i in range(1, (until - day).days + 1)]
    had = between(db, days[0], days[-1])
    was = {d: as_dicts(had.get(d, [])) for d in days}
    for d in days:
        _put_day(db, d, source)
    db.flush()
    return was


def _clean_items(items: Any) -> list[dict[str, Any]]:
    """Items as given (put): each a name, a value and sorted or not."""
    if not isinstance(items, list):
        raise DomainError("A stay is a list of items")
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise DomainError(f"Not a stay item: {item!r}")
        name = clean_name(item.get("name"))
        if any(i["name"].lower() == name.lower() for i in out):
            raise DomainError(f"{name} is in this stay twice")
        value = item.get("value", "")
        if not isinstance(value, str):
            raise DomainError(f"{name}'s value must be text")
        out.append(
            {"name": name, "value": " ".join(value.split()), "done": item.get("done") is True}
        )
    return out


def put(db: Session, stays: dict[date, Any]) -> None:
    """Each day's stay made as given, item for item (an empty list, none):
    days put back as they were (Undo)."""
    cleaned = {day: _clean_items(items) for day, items in stays.items()}
    for day, items in cleaned.items():
        _put_day(db, day, items)
    db.flush()


def _same(a: list[StayItem], b: list[StayItem]) -> bool:
    return [(i.name, i.value, i.done) for i in a] == [(i.name, i.value, i.done) for i in b]


def carried_to(db: Session, day: date) -> date | None:
    """The last of the days right after `day` whose stay is the same as
    its, item for item; None when the next day's is not."""
    items = items_on(db, day)
    if not items:
        return None
    after = between(db, day + timedelta(days=1), day + timedelta(days=MOST_DAYS))
    last = None
    next_day = day + timedelta(days=1)
    while _same(after.get(next_day, []), items):
        last = next_day
        next_day += timedelta(days=1)
    return last


def standing(db: Session, day: date) -> dict[str, Any]:
    """The day's stay as Today's stay pane draws it: its items (none, no
    stay), the items a stay written there starts with, those of them that
    are checkboxes, the last stay before it (to take again), the last day
    after it carrying it on, and each item's values written before."""
    items = items_on(db, day)
    names = [i.name for i in items] or starting_items(db, day)
    before = last_day_before(db, day)
    through = carried_to(db, day)
    return {
        "day": day.isoformat(),
        "items": as_dicts(items),
        "names": names,
        "checks": [name for name in names if is_check(name)],
        "before": None
        if before is None
        else {"day": before.isoformat(), "items": as_dicts(items_on(db, before))},
        "through": through.isoformat() if through else None,
        "values": values_used(db, names),
    }
