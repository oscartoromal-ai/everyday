"""View-model for the week calendar grid."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import BlockState, TaskOwner
from app.services import events as events_svc
from app.services import tasks as tasks_svc

DAY_START_HOUR = 6
DAY_END_HOUR = 22
HOUR_PX = 48
GRID_PX = (DAY_END_HOUR - DAY_START_HOUR) * HOUR_PX
# .cal-item metrics (app.css): 12px type at 1.3 line-height, 3px vertical padding.
ITEM_LINE_PX = 15.6
ITEM_PAD_PX = 6
ITEM_GAP_PX = 2
# A gutter label's line box (12px type at 1.3); the first hour's label sits 2px
# down from the top instead of centred on its line. Two labels' digits (about
# 9px tall) only collide when their centres are closer than GUTTER_CLEAR_PX.
GUTTER_LABEL_PX = 16
GUTTER_CLEAR_PX = 12


def _hour_label_centre(index: int) -> float:
    return 2 + GUTTER_LABEL_PX / 2 if index == 0 else index * HOUR_PX


def week_monday(anchor: date) -> date:
    return anchor - timedelta(days=anchor.weekday())


def _clamp_px(moment: datetime, day: date) -> float:
    day_start = datetime.combine(day, time(DAY_START_HOUR))
    minutes = (moment - day_start).total_seconds() / 60
    return max(0.0, min(GRID_PX, minutes / 60 * HOUR_PX))


def _position(start: datetime, end: datetime, day: date) -> dict[str, Any]:
    top = _clamp_px(start, day)
    bottom = _clamp_px(end, day)
    # A 2px gap at the foot keeps back-to-back items from merging into one slab.
    height = max(bottom - top - ITEM_GAP_PX, 20.0)
    # Long titles wrap into the item's height instead of truncating to "Priv…";
    # the time line only shows when there is room for it under the title.
    lines = max(1, int((height - ITEM_PAD_PX) // ITEM_LINE_PX))
    return {
        "top": round(top, 1),
        "height": round(height, 1),
        "title_lines": lines - 1 if lines >= 2 else 1,
        "show_time": lines >= 2,
    }


def _assign_lanes(items: list[dict[str, Any]]) -> None:
    """Greedy lane assignment so overlapping items sit side by side.

    Items must be sorted by start. Each cluster of transitively overlapping
    items shares a lane count; every item gets lane and lanes keys.
    """
    cluster: list[dict[str, Any]] = []
    cluster_end: datetime | None = None
    lane_ends: list[datetime] = []

    def close_cluster() -> None:
        for item in cluster:
            item["lanes"] = len(lane_ends)

    for item in items:
        if cluster_end is None or item["start"] < cluster_end:
            for lane, lane_end in enumerate(lane_ends):
                if item["start"] >= lane_end:
                    item["lane"] = lane
                    lane_ends[lane] = item["end"]
                    break
            else:
                item["lane"] = len(lane_ends)
                lane_ends.append(item["end"])
            cluster.append(item)
            cluster_end = max(cluster_end or item["end"], item["end"])
        else:
            close_cluster()
            cluster = [item]
            lane_ends = [item["end"]]
            item["lane"] = 0
            cluster_end = item["end"]
    close_cluster()


def grid_ctx(db: Session, first_day: date, now: datetime, day_count: int = 7) -> dict[str, Any]:
    """The time grid over `day_count` consecutive days from `first_day`: the
    week calendar (7 days from a Monday) and Today's timeline (1 day)."""
    week_days = [first_day + timedelta(days=i) for i in range(day_count)]
    range_start = datetime.combine(first_day, time.min)
    range_end = range_start + timedelta(days=day_count)
    events, blocks = events_svc.calendar_range(db, range_start, range_end)
    today = now.date()

    days: list[dict[str, Any]] = []
    for day in week_days:
        day_items: list[dict[str, Any]] = []
        all_day: list[dict[str, Any]] = []
        for event in events:
            if event.start.date() > day or event.end.date() < day:
                continue
            if event.all_day:
                all_day.append({"title": event.title, "source": event.source.value})
                continue
            if event.start.date() != day and event.start.date() < day:
                start = datetime.combine(day, time.min)
            else:
                start = event.start
            location = event.location
            # Meeting-link locations stay in the tooltip; a URL is noise on the grid.
            location_label = "" if location.startswith(("http://", "https://")) else location
            day_items.append(
                {
                    "kind": "event",
                    "id": event.id,
                    "title": event.title,
                    "location": location,
                    "location_label": location_label,
                    "source": event.source.value,
                    "start": start,
                    "end": event.end,
                    "time_label": f"{event.start:%H:%M}",
                }
            )
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
        day_items.sort(key=lambda i: i["start"])
        _assign_lanes(day_items)
        for item in day_items:
            item.update(_position(item["start"], item["end"], day))
            item["start_iso"] = item["start"].isoformat()
            item["end_iso"] = item["end"].isoformat()
        days.append(
            {
                "date": day,
                "is_today": day == today,
                "entries": day_items,  # "items" would shadow dict.items in Jinja
                "all_day": all_day,
            }
        )

    now_px = None
    if first_day <= today < first_day + timedelta(days=day_count):
        px = _clamp_px(now, today)
        if 0 < px < GRID_PX:
            now_px = round(px, 1)

    # The now-label covers the gutter where it sits; an hour label it would half
    # cover gives way instead of peeking out above or below it.
    hours = list(range(DAY_START_HOUR, DAY_END_HOUR))
    hours_under_now = [
        i for i in range(len(hours))
        if now_px is not None and abs(_hour_label_centre(i) - now_px) < GUTTER_CLEAR_PX
    ]

    return {
        "days": days,
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
        "prev_week": (first_day - timedelta(days=7)).isoformat(),
        "next_week": (first_day + timedelta(days=7)).isoformat(),
        "week_label": _week_label(first_day),
    }


def strip_ctx(db: Session, day: date, now: datetime) -> dict[str, Any]:
    """A day's time as a horizontal scale (a day page's strip): the same
    items as the one-day grid, placed by percent of the day's span, with
    overlapping ones in lanes."""
    grid = grid_ctx(db, day, now, day_count=1)
    column = grid["days"][0]
    origin = datetime.combine(day, time(DAY_START_HOUR))
    span = (DAY_END_HOUR - DAY_START_HOUR) * 60

    def pct(moment: datetime) -> float:
        return max(0.0, min(100.0, (moment - origin).total_seconds() / 60 / span * 100))

    items = []
    for item in column["entries"]:
        left, right = pct(item["start"]), pct(item["end"])
        if right <= left:
            continue  # wholly outside the scale's hours
        items.append({**item, "left": round(left, 3), "width": round(right - left, 3)})
    lanes = max((i["lanes"] for i in items), default=1)
    hours = [
        {"label": f"{h:02d}", "left": round((h - DAY_START_HOUR) * 60 / span * 100, 3)}
        for h in range(DAY_START_HOUR, DAY_END_HOUR + 1)
    ]
    now_pct = None
    if day == now.date():
        value = pct(now)
        if 0 < value < 100:
            now_pct = round(value, 3)
    return {
        "day": day,
        "items": items,
        "lanes": lanes,
        "hours": hours,
        "all_day": column["all_day"],
        "now_pct": now_pct,
        "now_label": f"{now:%H:%M}",
        "start_hour": DAY_START_HOUR,
        "end_hour": DAY_END_HOUR,
    }


def _week_label(week_start: date) -> str:
    week_end = week_start + timedelta(days=6)
    if week_start.month == week_end.month:
        return f"{week_start.day}–{week_end.day} {week_end.strftime('%B %Y')}"
    return (
        f"{week_start.day} {week_start.strftime('%b')} – "
        f"{week_end.day} {week_end.strftime('%b')} {week_end.strftime('%Y')}"
    )


def tray_tasks(db: Session, week_start: date, now: datetime) -> list[dict[str, Any]]:
    """Open tasks worth dragging onto this week: planned or due this week,
    fallen-back missed tasks, and a slice of the backlog."""
    week_end = week_start + timedelta(days=6)
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
                "project_name": task.project.name if task.project else None,
            }
        )

    for task in tasks_svc.list_tasks(db, planned_from=week_start, planned_to=week_end):
        if task.status in tasks_svc.OPEN_STATUSES:
            add(task, "planned")
    for task in tasks_svc.list_tasks(db):
        if task.status in tasks_svc.OPEN_STATUSES and tasks_svc.has_missed_marker(task, now):
            add(task, "missed")
        elif (
            task.status in tasks_svc.OPEN_STATUSES
            and task.due is not None
            and week_start <= task.due <= week_end
        ):
            add(task, "due")
    for task in tasks_svc.backlog(db)[:8]:
        add(task, "backlog")
    return out[:24]
