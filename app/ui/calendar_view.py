"""View-model for the calendar's time grid: Calendar's day, three days and
week, and Today's timeline."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.dates import duration_label, short_date, upper_first
from app.models import BlockState, Task, TaskOwner
from app.services import blocks as blocks_svc
from app.services import events as events_svc
from app.services import recurrence as recurrence_svc
from app.services import tasks as tasks_svc

# The usual day: where the grid opens, and where the next free slot is looked
# for. The grid itself runs the whole day, so nothing is squeezed to its edge.
DAY_START_HOUR = 6
DAY_END_HOUR = 22
HOUR_PX = 48
GRID_PX = 24 * HOUR_PX
# .cal-item metrics (app.css): 12px type at 1.3 line-height, 3px vertical padding.
ITEM_LINE_PX = 15.6
ITEM_PAD_PX = 6
ITEM_GAP_PX = 2
# The shortest an item is drawn, so a five-minute meeting still shows its title.
ITEM_MIN_PX = 20.0
# A gutter label's line box (12px type at 1.3); the first hour's label sits 2px
# down from the top instead of centred on its line. Two labels' digits (about
# 9px tall) only collide when their centres are closer than GUTTER_CLEAR_PX.
GUTTER_LABEL_PX = 16
GUTTER_CLEAR_PX = 12
# Items starting this close together sit side by side; one starting later is
# laid over those still running, stepped in by STACK_INDENT_PX, so theirs
# keep their full width and their titles. The steps stop at STACK_MAX_DEPTH.
STACK_GAP = timedelta(minutes=30)
STACK_INDENT_PX = 14
STACK_MAX_DEPTH = 3

# Calendar's views: how many days each shows.
VIEWS = {"day": 1, "3days": 3, "week": 7}
VIEW_LABELS = {"day": "Day", "3days": "3 days", "week": "Week"}
VIEW_KEYS = {"day": "D", "3days": "X", "week": "W"}


def _hour_label_centre(index: int) -> float:
    return 2 + GUTTER_LABEL_PX / 2 if index == 0 else index * HOUR_PX


def week_monday(anchor: date) -> date:
    return anchor - timedelta(days=anchor.weekday())


def view_start(view: str, anchor: date) -> date:
    """The first day a view shows around `anchor`: a week from its Monday,
    fewer days from the day itself."""
    return week_monday(anchor) if view == "week" else anchor


def _clamp_px(moment: datetime, day: date) -> float:
    minutes = (moment - datetime.combine(day, time.min)).total_seconds() / 60
    return max(0.0, min(GRID_PX, minutes / 60 * HOUR_PX))


def _drawn_end(item: dict[str, Any]) -> datetime:
    """Where an item's box ends on the grid: a short one is drawn taller than
    it lasts, and lays out as drawn, so nothing is placed over its title."""
    shortest = timedelta(minutes=(ITEM_MIN_PX + ITEM_GAP_PX) / HOUR_PX * 60)
    return max(item["end"], item["start"] + shortest)


def _position(
    start: datetime, end: datetime, day: date, text_until: datetime | None = None
) -> dict[str, Any]:
    top = _clamp_px(start, day)
    bottom = _clamp_px(end, day)
    # A 2px gap at the foot keeps back-to-back items from merging into one slab.
    height = max(bottom - top - ITEM_GAP_PX, ITEM_MIN_PX)
    # Long titles wrap into the item's height instead of truncating to "Priv…";
    # the time line only shows when there is room for it under the title. An
    # item laid over this one (text_until) covers the rest, so the words stop
    # above it rather than peek out beside it.
    room = height
    if text_until is not None:
        room = min(room, max(_clamp_px(text_until, day) - top - ITEM_GAP_PX, ITEM_MIN_PX))
    lines = max(1, int((room - ITEM_PAD_PX) // ITEM_LINE_PX))
    return {
        "top": round(top, 1),
        "height": round(height, 1),
        "title_lines": lines - 1 if lines >= 2 else 1,
        "show_time": lines >= 2,
    }


def _layout(items: list[dict[str, Any]]) -> None:
    """Place a day's items across its column, as Google Calendar does.

    Items must be sorted by start (the longer first on a tie). Items that
    start within STACK_GAP of each other and overlap form a group, side by
    side in lanes. A group starting later, over items still running, is laid
    on top of them, stepped in a little further each time it nests: the item
    under it keeps its width, so its title stays readable.

    Every item gets lane, lanes (its group's lane count), depth (how far it
    is stepped in, 0 for none) and covered_from (when the first item laid
    over it starts, or None).
    """
    groups: list[dict[str, Any]] = []
    for item in items:
        end = _drawn_end(item)
        last = groups[-1] if groups else None
        if last and item["start"] - last["start"] < STACK_GAP and item["start"] < last["end"]:
            group = last
        else:
            running = [g for g in groups if g["end"] > item["start"]]
            for g in running:
                for under in g["items"]:
                    if _drawn_end(under) > item["start"] and under.get("covered_from") is None:
                        under["covered_from"] = item["start"]
            group = {
                "start": item["start"],
                "end": end,
                "depth": min(max((g["depth"] for g in running), default=-1) + 1, STACK_MAX_DEPTH),
                "lane_ends": [],
                "items": [],
            }
            groups.append(group)
        item["covered_from"] = None
        for lane, lane_end in enumerate(group["lane_ends"]):
            if item["start"] >= lane_end:
                group["lane_ends"][lane] = end
                item["lane"] = lane
                break
        else:
            item["lane"] = len(group["lane_ends"])
            group["lane_ends"].append(end)
        group["end"] = max(group["end"], end)
        group["items"].append(item)
    for group in groups:
        for item in group["items"]:
            item["lanes"] = len(group["lane_ends"])
            item["depth"] = group["depth"]


def _single_day(start: datetime, end: datetime) -> bool:
    """Whether a timed item lies within one day (ending at the next midnight
    counts), so dragging it on that day's column means what it shows."""
    next_midnight = datetime.combine(start.date(), time.min) + timedelta(days=1)
    return end.date() == start.date() or end == next_midnight


def _event_entry(event, day: date) -> dict[str, Any]:  # noqa: ANN001
    start = event.start if event.start.date() == day else datetime.combine(day, time.min)
    location = event.location
    # Meeting-link locations stay in the event's card; a URL is noise on the grid.
    location_label = "" if location.startswith(("http://", "https://")) else location
    return {
        "kind": "event",
        "id": event.id,
        "title": event.shown_title,
        "location": location,
        "location_label": location_label,
        "source": event.source.value,
        "cancelled": event.cancelled,
        "movable": not event.read_only and _single_day(event.start, event.end),
        "start": start,
        "end": event.end,
        "time_label": f"{event.start:%H:%M}",
    }


def _floor_quarter(minutes: float) -> int:
    return int(minutes // 15 * 15)


def day_load(db: Session, day: date, now: datetime, planned: list[Task]) -> dict[str, Any] | None:
    """Whether a day's plan fits it: the time already taken in its usual
    hours (meetings and blocks), what its planned tasks without a time are
    estimated at, and the time still free (today's from now). None for a day
    already past."""
    if day < now.date():
        return None
    window_start = datetime.combine(day, time(DAY_START_HOUR))
    window_end = datetime.combine(day, time(DAY_END_HOUR))
    if day == now.date():
        window_start = min(max(window_start, now), window_end)
    booked = sum(
        ((e - s) for s, e in blocks_svc.busy_spans(db, window_start, window_end)),
        timedelta(),
    )
    free = _floor_quarter(((window_end - window_start) - booked).total_seconds() / 60)
    booked_minutes = round(booked.total_seconds() / 60)
    planned_minutes = sum(
        t.estimate_minutes or 0
        for t in planned
        if t.planned_for == day
        and not any(
            b.state != BlockState.missed and b.start.date() == day for b in t.blocks
        )
    )
    since = "from now" if day == now.date() else f"from {DAY_START_HOUR:02d}:00"
    parts = [f"{duration_label(booked_minutes)} booked" if booked_minutes else "nothing booked"]
    if planned_minutes:
        parts.append(f"{duration_label(planned_minutes)} of tasks planned without a time")
    parts.append(
        f"{duration_label(free) if free else 'no time'} free {since} to {DAY_END_HOUR:02d}:00"
    )
    return {
        "planned": duration_label(planned_minutes) if planned_minutes else "",
        "free": duration_label(free) if free else "0m",
        "over": planned_minutes > free,
        "title": upper_first(", ".join(parts)),
    }


def grid_ctx(
    db: Session,
    first_day: date,
    now: datetime,
    day_count: int = 7,
    *,
    head: bool | None = None,
) -> dict[str, Any]:
    """The time grid over `day_count` consecutive days from `first_day`:
    Calendar's views (1, 3 or 7 days, each day headed) and Today's timeline
    (1 day, its page naming the day, so `head` defaults off for it)."""
    head = day_count > 1 if head is None else head
    week_days = [first_day + timedelta(days=i) for i in range(day_count)]
    range_start = datetime.combine(first_day, time.min)
    range_end = range_start + timedelta(days=day_count)
    events, blocks = events_svc.calendar_range(db, range_start, range_end)
    today = now.date()
    planned = [
        t for t in tasks_svc.list_tasks(
            db, planned_from=first_day, planned_to=week_days[-1]
        )
        if t.owner == TaskOwner.oscar and t.status in tasks_svc.OPEN_STATUSES
    ]

    days: list[dict[str, Any]] = []
    for day in week_days:
        day_items: list[dict[str, Any]] = []
        all_day: list[dict[str, Any]] = []
        for event in events:
            if event.start.date() > day or event.end <= datetime.combine(day, time.min):
                continue  # not on this day, or ended at the midnight it starts
            if event.all_day:
                all_day.append(
                    {
                        "id": event.id,
                        "title": event.shown_title,
                        "source": event.source.value,
                        "cancelled": event.cancelled,
                    }
                )
                continue
            day_items.append(_event_entry(event, day))
        for block in blocks:
            if block.start.date() != day:
                continue
            if block.state == BlockState.missed and day != today:
                continue  # the past stays honest: old missed slots vanish
            day_items.append(
                {
                    "kind": "ghost" if block.state == BlockState.missed else "block",
                    "id": block.id,
                    "title": block.task.title,
                    "task_id": block.task_id,
                    "state": block.state.value,
                    "start": block.start,
                    "end": block.end,
                    "time_label": f"{block.start:%H:%M}",
                }
            )
        day_items.sort(key=lambda i: (i["start"], i["start"] - i["end"]))
        _layout(day_items)
        for item in day_items:
            item.update(_position(item["start"], item["end"], day, item["covered_from"]))
            item["indent_px"] = item["depth"] * STACK_INDENT_PX
            item["start_iso"] = item["start"].isoformat()
            item["end_iso"] = item["end"].isoformat()
        days.append(
            {
                "date": day,
                "is_today": day == today,
                "is_weekend": day.weekday() >= 5,
                "entries": day_items,  # "items" would shadow dict.items in Jinja
                "all_day": all_day,
                "load": day_load(db, day, now, planned),
            }
        )

    now_px = None
    if first_day <= today < first_day + timedelta(days=day_count):
        px = _clamp_px(now, today)
        if 0 < px < GRID_PX:
            now_px = round(px, 1)

    # The now-label covers the gutter where it sits; an hour label it would half
    # cover gives way instead of peeking out above or below it.
    hours = list(range(24))
    hours_under_now = [
        i for i in range(len(hours))
        if now_px is not None and abs(_hour_label_centre(i) - now_px) < GUTTER_CLEAR_PX
    ]

    return {
        "days": days,
        "head": head,
        "hours": hours,
        "hours_under_now": hours_under_now,
        "hour_px": HOUR_PX,
        "grid_px": GRID_PX,
        "day_start_hour": DAY_START_HOUR,
        "now_px": now_px,
        "now_label": f"{now:%H:%M}",
        "today": today,
        "start": first_day,
        "day_count": day_count,
        "label": range_label(first_day, day_count),
    }


def range_label(first_day: date, day_count: int) -> str:
    """The days a view shows, as its page's title."""
    if day_count == 1:
        return f"{first_day:%A} {first_day.day} {first_day:%B %Y}"
    last_day = first_day + timedelta(days=day_count - 1)
    if first_day.year != last_day.year:
        return f"{first_day.day} {first_day:%b %Y} – {last_day.day} {last_day:%b %Y}"
    if first_day.month == last_day.month:
        return f"{first_day.day}–{last_day.day} {last_day:%B %Y}"
    return f"{first_day.day} {first_day:%b} – {last_day.day} {last_day:%b %Y}"


def calendar_nav(view: str, first_day: date, today: date) -> dict[str, Any]:
    """Calendar's header: the view switch's links, and the steps back and on
    by the view's own length."""
    day_count = VIEWS[view]
    shows_today = first_day <= today < first_day + timedelta(days=day_count)
    # A switch keeps today in view if it is, else the first day shown.
    anchor = today if shows_today else first_day
    return {
        "view": view,
        "views": [
            {
                "key": key,
                "label": VIEW_LABELS[key],
                "shortcut": VIEW_KEYS[key],
                "start": view_start(key, anchor).isoformat(),
            }
            for key in VIEWS
        ],
        "prev": (first_day - timedelta(days=day_count)).isoformat(),
        "next": (first_day + timedelta(days=day_count)).isoformat(),
    }


def event_card_ctx(event, today: date) -> dict[str, Any]:  # noqa: ANN001
    """An event's card: what it is, when and where, and for one of Oscar's
    own, its fields to change."""
    location = event.location.strip()
    link = location if location.startswith(("http://", "https://")) else ""
    repeat = ""
    if event.recurrence_template is not None:
        repeat = {
            "daily": "Repeats daily",
            "weekdays": "Repeats on weekdays",
            "weekly": "Repeats weekly",
            "monthly": "Repeats monthly",
        }[recurrence_svc.preset_of(event.recurrence_template)]
    last_day = event.end.date() - timedelta(days=1) if event.all_day else event.end.date()
    return {
        "event": event,
        "title": event.shown_title,
        "cancelled": event.cancelled,
        "when": _when_label(event, last_day, today),
        "link": link,
        "link_host": link_host(link),
        "place": "" if link else location,
        "repeat": repeat,
        "day": event.start.date().isoformat(),
        "start_time": "" if event.all_day else f"{event.start:%H:%M}",
        "end_time": "" if event.all_day else f"{event.end:%H:%M}",
    }


def _when_label(event, last_day: date, today: date) -> str:  # noqa: ANN001
    first_day = event.start.date()
    day = upper_first(short_date(first_day, today))
    if event.all_day:
        if last_day > first_day:
            return f"{day} – {short_date(last_day, today)}, all day"
        return f"{day}, all day"
    if last_day > first_day:
        return f"{day} {event.start:%H:%M} – {short_date(last_day, today)} {event.end:%H:%M}"
    return f"{day}, {event.start:%H:%M}–{event.end:%H:%M}"


def link_host(url: str) -> str:
    """A meeting link's service, as its Join button names it: "zoom.us"."""
    if not url:
        return ""
    host = url.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0].lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def tray_tasks(
    db: Session, first_day: date, now: datetime, day_count: int = 7
) -> list[dict[str, Any]]:
    """Open tasks worth giving time in the days shown: planned or due in them,
    fallen-back missed tasks, and a slice of the backlog."""
    last_day = first_day + timedelta(days=day_count - 1)
    seen: set[int] = set()
    out: list[dict[str, Any]] = []

    def add(task, reason: str) -> None:  # noqa: ANN001
        if task.id in seen or task.owner != TaskOwner.oscar:
            return
        # Already slotted into protected time ahead: nothing left to schedule.
        if any(b.state == BlockState.planned and b.start >= now for b in task.blocks):
            return
        seen.add(task.id)
        out.append(
            {
                "task": task,
                "reason": reason,
                "project": task.project,
            }
        )

    for task in tasks_svc.list_tasks(db, planned_from=first_day, planned_to=last_day):
        if task.status in tasks_svc.OPEN_STATUSES:
            add(task, "planned")
    for task in tasks_svc.list_tasks(db):
        if task.status in tasks_svc.OPEN_STATUSES and tasks_svc.has_missed_marker(task, now):
            add(task, "missed")
        elif (
            task.status in tasks_svc.OPEN_STATUSES
            and task.due is not None
            and first_day <= task.due <= last_day
        ):
            add(task, "due")
    for task in tasks_svc.backlog(db)[:8]:
        add(task, "backlog")
    return out[:24]
