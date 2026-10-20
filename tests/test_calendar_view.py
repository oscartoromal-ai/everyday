"""Calendar's time grid: how a day's items share its column, cancelled
meetings, the day / three days / week views, and an event's card."""

import re
from datetime import date, datetime, time, timedelta

from app.models import Event, EventSource
from app.services import events as events_svc
from app.services import recurrence as recurrence_svc
from app.ui.calendar_view import grid_ctx

DAY = date(2026, 9, 28)  # a Monday
TODAY = date.today()


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute))


def work(db, title: str, start: datetime, end: datetime, *, all_day: bool = False) -> Event:
    event = Event(
        title=title, start=start, end=end, all_day=all_day,
        source=EventSource.work, read_only=True, external_id=f"{title}:{start}",
    )
    db.add(event)
    db.flush()
    return event


def items_of(db, day: date = DAY) -> dict[str, dict]:
    grid = grid_ctx(db, day, at(8, day=day), day_count=1)
    return {item["title"]: item for item in grid["days"][0]["entries"]}


def test_items_starting_together_sit_side_by_side_and_later_ones_lie_over(db) -> None:
    work(db, "Long review", at(13), at(15))
    work(db, "Apply", at(12), at(13))
    work(db, "Futsal", at(12, 15), at(13, 30))
    work(db, "Late check-in", at(14, 30), at(15))
    items = items_of(db)
    # 15 minutes apart: two lanes, side by side, neither stepped in.
    assert (items["Apply"]["lane"], items["Apply"]["lanes"]) == (0, 2)
    assert (items["Futsal"]["lane"], items["Futsal"]["lanes"]) == (1, 2)
    assert items["Apply"]["depth"] == items["Futsal"]["depth"] == 0
    # The review starts under Futsal's last half hour: laid over it, stepped in.
    assert items["Long review"]["depth"] == 1
    # Starting an hour and a half into the review: laid over that, a step
    # further in, the review keeping its whole width.
    assert items["Long review"]["lanes"] == items["Late check-in"]["lanes"] == 1
    assert items["Late check-in"]["depth"] == 2


def test_an_item_laid_over_another_stops_the_words_under_it(db) -> None:
    work(db, "Quarterly planning review - what happened - follow-up notes", at(13), at(15))
    work(db, "Standup", at(14, 30), at(15))
    alone = grid_ctx(db, DAY, at(8), day_count=1)["days"][0]["entries"]
    under = next(i for i in alone if i["title"].startswith("Quarterly planning"))
    # 90 minutes (72px) above the item laid over it: three lines and the time,
    # not the six lines its whole two hours would take.
    assert under["covered_from"] == at(14, 30)
    assert under["title_lines"] == 3 and under["show_time"]


def test_a_short_meeting_lays_out_as_tall_as_it_is_drawn(db) -> None:
    # Five minutes, drawn 20px (25 minutes) tall: the 12:15 meeting would
    # land on its title, so the two sit side by side instead.
    work(db, "Metrics sync", at(12), at(12, 5))
    work(db, "Budget review", at(12, 15), at(12, 45))
    items = items_of(db)
    assert items["Metrics sync"]["lanes"] == items["Budget review"]["lanes"] == 2


def test_a_cancelled_meeting_shows_struck_and_takes_no_time(db) -> None:
    cancelled = work(db, "Canceled: Team sync", at(9), at(10))
    assert cancelled.cancelled and cancelled.shown_title == "Team sync"
    assert not work(db, "Cancellation policy review", at(11), at(12)).cancelled
    item = items_of(db)["Team sync"]
    assert item["cancelled"]
    # The hour is free.
    assert events_svc.busy_spans(db, at(9), at(10)) == []


def test_an_all_day_event_shows_on_its_own_day_only(db) -> None:
    work(db, "Holiday", at(0), at(0, day=DAY + timedelta(days=1)), all_day=True)
    grid = grid_ctx(db, DAY, at(8), day_count=2)
    assert [e["title"] for e in grid["days"][0]["all_day"]] == ["Holiday"]
    assert grid["days"][1]["all_day"] == []


def test_the_grid_runs_the_whole_day(db) -> None:
    work(db, "Late flight", at(22, 30), at(23, 45))
    grid = grid_ctx(db, DAY, at(8), day_count=1)
    assert grid["hours"] == list(range(24))
    [item] = grid["days"][0]["entries"]
    assert item["top"] == 22.5 * 48  # no longer squeezed to a 22:00 edge


def test_calendar_shows_a_day_three_days_or_a_week(client) -> None:
    friday = DAY + timedelta(days=4)
    day = client.get(f"/calendar?view=day&start={friday.isoformat()}").text
    assert "Friday 2 October 2026" in day and day.count('class="day-col') == 1
    three = client.get(f"/calendar?view=3days&start={friday.isoformat()}").text
    assert "2–4 October 2026" in three and three.count('class="day-col') == 3
    # Saturday and Sunday are tinted wherever they fall.
    assert len(re.findall(r'class="day-col[^"]* weekend"', three)) == 2
    week = client.get(f"/calendar?view=week&start={friday.isoformat()}").text
    assert "28 Sep – 4 Oct 2026" in week and week.count('class="day-col') == 7
    # Each view's steps go by its own length.
    assert 'href="/calendar?start=2026-10-05" aria-label="Later"' in three
    assert 'href="/calendar?start=2026-09-29" aria-label="Earlier"' in three


def test_the_view_is_remembered_and_a_phone_starts_on_three_days(client) -> None:
    client.cookies.delete("calendar_view")
    phone = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148 Safari/604.1"}
    page = client.get("/calendar", headers=phone)
    assert page.text.count('class="day-col') == 3
    assert "calendar_view" not in page.cookies  # a default, not a choice
    assert client.get("/calendar").text.count('class="day-col') == 7

    client.get("/calendar?view=day")
    assert client.get("/calendar").text.count('class="day-col') == 1
    assert client.get("/calendar", headers=phone).text.count('class="day-col') == 1
    # The week view's old links still open on their week.
    old = client.get(f"/calendar?view=week&week={(DAY + timedelta(days=2)).isoformat()}").text
    assert f'data-start="{DAY.isoformat()}"' in old


def test_a_view_switch_keeps_today_in_view(client) -> None:
    monday = TODAY - timedelta(days=TODAY.weekday())
    page = client.get(f"/calendar?view=week&start={monday.isoformat()}").text
    assert f'href="/calendar?view=day&start={TODAY.isoformat()}"' in page
    later = monday + timedelta(weeks=3)
    page = client.get(f"/calendar?view=week&start={later.isoformat()}").text
    assert f'href="/calendar?view=day&start={later.isoformat()}"' in page


def test_a_work_meetings_card_reads_and_joins(client, db) -> None:
    event = work(db, "Design review - Roadmap", at(11, 30), at(12, 30))
    event.location = "https://example.zoom.us/j/123456789?from=addon"
    db.flush()
    card = client.get(f"/ui/events/{event.id}/card").text
    assert "Design review - Roadmap" in card
    assert "11:30–12:30" in card
    assert 'href="https://example.zoom.us/j/123456789?from=addon"' in card
    assert "Join on zoom.us" in card
    assert "read-only" in card and "<form" not in card
    # Nothing it changes reaches a work meeting.
    response = client.post(
        f"/ui/events/{event.id}", data={"title": "Mine", "day": DAY.isoformat()}
    )
    assert response.status_code == 422


def test_an_own_event_is_changed_and_deleted_on_its_card(client, db) -> None:
    event = events_svc.create_event(db, title="Dentist", start=at(9), end=at(10))
    card = client.get(f"/ui/events/{event.id}/card").text
    assert 'value="Dentist"' in card and 'value="09:00"' in card
    response = client.post(
        f"/ui/events/{event.id}",
        data={
            "title": "Dentist, Dr Ruiz", "day": DAY.isoformat(),
            "start_time": "09:30", "end_time": "10:15",
        },
    )
    assert response.headers["hx-trigger"] == "calendar:refresh"
    db.refresh(event)
    assert (event.title, event.start, event.end) == ("Dentist, Dr Ruiz", at(9, 30), at(10, 15))
    # No times: all day, as when one is added.
    client.post(f"/ui/events/{event.id}", data={"title": "Dentist", "day": DAY.isoformat()})
    db.refresh(event)
    assert event.all_day and event.end - event.start == timedelta(days=1)
    client.post(f"/ui/events/{event.id}/delete")
    assert db.get(Event, event.id) is None


def test_deleting_one_of_a_series_and_the_rest_from_it(client, db) -> None:
    template = recurrence_svc.create_template(
        db, kind=recurrence_svc.RecurrenceKind.event, repeat="daily", start_date=TODAY,
        title="Stretch", start_time="07:00", end_time="07:15",
    )
    recurrence_svc.materialize_template(db, template, TODAY)
    db.commit()

    def series() -> list[Event]:
        return sorted(
            (e for e in db.query(Event).all() if e.recurrence_template_id == template.id),
            key=lambda e: e.start,
        )

    first, second, third, *_ = series()
    assert "Repeats daily" in client.get(f"/ui/events/{second.id}/card").text
    client.post(f"/ui/events/{second.id}/delete", data={"scope": "one"})
    db.expire_all()
    assert second.id not in [e.id for e in series()]
    client.post(f"/ui/events/{third.id}/delete", data={"scope": "following"})
    db.expire_all()
    assert [e.id for e in series()] == [first.id]


def test_a_days_load_weighs_its_planned_tasks_against_its_free_time(db) -> None:
    from app.services import tasks as tasks_svc
    from app.ui.calendar_view import day_load

    tuesday = DAY + timedelta(days=1)
    work(db, "Workshop", at(9, day=tuesday), at(13, day=tuesday))
    work(db, "Overlapping catch-up", at(12, day=tuesday), at(14, day=tuesday))
    work(db, "Canceled: Retro", at(15, day=tuesday), at(16, day=tuesday))
    tasks_svc.create_task(db, title="Write", planned_for=tuesday, estimate_minutes=90)
    tasks_svc.create_task(db, title="Review", planned_for=tuesday, estimate_minutes=60)
    tasks_svc.create_task(db, title="No estimate", planned_for=tuesday)
    db.flush()
    planned = tasks_svc.list_tasks(db)
    load = day_load(db, tuesday, at(8), planned)
    # 06:00-22:00 is 16h; 09:00-14:00 takes 5h (the cancelled retro none);
    # the estimates add up to 2h 30m.
    assert (load["planned"], load["free"], load["over"]) == ("2h 30m", "11h", False)
    assert load["title"] == "5h booked, 2h 30m of tasks planned, 11h free from 06:00 to 22:00"
    # Today's free time runs from now, and the plan no longer fits it; a day
    # gone has no load.
    today_load = day_load(db, tuesday, at(20, 10, day=tuesday), planned)
    assert (today_load["free"], today_load["over"]) == ("1h 45m", True)
    assert day_load(db, DAY, at(8, day=tuesday), planned) is None


def test_each_day_shows_its_load_on_calendar_and_today(client, db) -> None:
    from app.services import tasks as tasks_svc

    tasks_svc.create_task(db, title="Write", planned_for=TODAY, estimate_minutes=45)
    week = client.get("/calendar?view=week").text
    assert '<span class="planned">45m planned</span>' in week
    assert 'class="day-head' in client.get("/calendar?view=day").text  # its head carries it
    today = client.get("/today").text
    assert 'class="grid-load"' in today and "45m planned" in today


def test_the_header_names_the_iso_weeks_shown(client) -> None:
    from app.ui.calendar_view import weeks_label

    assert weeks_label(DAY, 7, DAY) == "W40"
    assert weeks_label(DAY + timedelta(days=5), 3, DAY) == "W40–41"
    # Another year's weeks say their year.
    assert weeks_label(date(2027, 1, 4), 1, DAY) == "W1 '27"
    assert weeks_label(date(2026, 12, 31), 7, DAY) == "W53 – W1 '27"
    page = client.get(f"/calendar?view=week&start={DAY.isoformat()}").text
    assert '<span class="week-number" title="ISO week">W40</span>' in page
    assert f'data-jump-date value="{DAY.isoformat()}"' in page


def test_the_hour_label_under_the_now_label_gives_way(db) -> None:
    from app.ui.calendar_view import week_monday

    monday = week_monday(DAY)
    # 15:05 sits 4px under the 15:00 line: that label would peek out, so it hides.
    assert grid_ctx(db, monday, at(15, 5))["hours_under_now"] == [15]
    # 06:41 comes within a line box of 07:00, but the digits never meet: it stays.
    assert grid_ctx(db, monday, at(6, 41))["hours_under_now"] == []
    # 15:30 is clear of both 15:00 and 16:00.
    assert grid_ctx(db, monday, at(15, 30))["hours_under_now"] == []
    # 06:10 is 8px under the 06:00 line.
    assert grid_ctx(db, monday, at(6, 10))["hours_under_now"] == [6]
    # 00:10 is just under the first label, which sits 2px from the top.
    assert grid_ctx(db, monday, at(0, 10))["hours_under_now"] == [0]
