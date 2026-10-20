"""Today's layout: its panes in three columns in the order dragged, panes
hidden in their places, kept as a setting (app/services/today_layout.py).
test_today_layout_browser.py drags, hides and shows them in a browser."""

import pytest

from app.services import DomainError
from app.services import today_layout as today_layout_svc


def placed(db) -> list[tuple[str, list[str]]]:
    return [(c.key, [p.pane.key for p in c.panes]) for c in today_layout_svc.layout(db)]


def hidden(db) -> set[str]:
    return {p.pane.key for c in today_layout_svc.layout(db) for p in c.panes if p.hidden}


def test_today_starts_with_the_plan_and_habits_the_notes_and_the_timeline(db) -> None:
    assert placed(db) == [
        ("left", ["plan", "habits"]),
        ("center", ["notes"]),
        ("right", ["timeline"]),
    ]
    assert hidden(db) == set()
    assert placed(None) == placed(db)
    assert today_layout_svc.default_columns() == [["plan", "habits"], ["notes"], ["timeline"]]


def test_panes_keep_the_columns_and_order_they_are_dragged_to(db) -> None:
    today_layout_svc.save_layout(
        db, columns=[["notes"], [], ["habits", "timeline", "plan"]], hidden=["timeline"]
    )
    db.commit()
    assert placed(db) == [
        ("left", ["notes"]),
        ("center", []),
        ("right", ["habits", "timeline", "plan"]),
    ]
    # A hidden pane keeps its place; a column with none showing is empty.
    assert hidden(db) == {"timeline"}
    columns = {c.key: c for c in today_layout_svc.layout(db)}
    assert columns["center"].empty
    assert not columns["right"].empty


def test_a_pane_not_placed_joins_its_own_column_and_one_placed_twice_counts_once(db) -> None:
    # As a layout saved before a pane was added to the code reads: the
    # pane the save does not name starts where the code puts it.
    today_layout_svc.save_layout(db, columns=[["timeline", "notes"], ["notes"], []], hidden=[])
    db.commit()
    assert placed(db) == [
        ("left", ["timeline", "notes", "plan", "habits"]),
        ("center", []),
        ("right", []),
    ]


def test_a_pane_or_a_column_count_the_code_does_not_know_is_refused(db) -> None:
    with pytest.raises(DomainError):
        today_layout_svc.save_layout(db, columns=[["plan"], ["weather"], []], hidden=[])
    with pytest.raises(DomainError):
        today_layout_svc.save_layout(db, columns=[["plan"], []], hidden=[])
    with pytest.raises(DomainError):
        today_layout_svc.save_layout(db, columns=[[], [], []], hidden=["weather"])


def test_the_day_page_draws_its_panes_where_they_were_left(client, db) -> None:
    response = client.put(
        "/ui/today/layout",
        json={"columns": [["timeline"], ["notes"], ["plan", "habits"]], "hidden": ["habits"]},
    )
    assert response.status_code == 204
    html = client.get("/today").text
    # The timeline in the left column, the plan and the hidden habits at the right.
    left = html.index('data-col="left"')
    center = html.index('data-col="center"')
    right = html.index('data-col="right"')
    assert left < html.index('data-pane="timeline"') < center
    assert right < html.index('data-pane="plan"') < html.index('data-pane="habits"')
    habits = html[html.index('data-pane="habits"') :]
    assert " hidden>" in habits[: habits.index(">") + 1]
    assert 'data-cols="lcr"' in html
    # The left column's fold is named for what is in it now.
    assert 'aria-label="Fold Timeline away"' in html


def test_a_column_folded_or_with_nothing_showing_is_not_drawn(client, db) -> None:
    client.put(
        "/ui/today/layout",
        json={"columns": [["plan", "habits"], ["notes"], ["timeline"]], "hidden": ["timeline"]},
    )
    client.cookies.set("today_folded", "left.habits")
    html = client.get("/today").text
    assert 'data-cols="c"' in html
    assert 'aria-label="Show Plan and Habits"' in html
