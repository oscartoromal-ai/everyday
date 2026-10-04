"""The sidebar's layout: sections and modules in the order dragged, modules
hidden, kept as a setting; and the projects' own order (app/services/rail.py,
projects.reorder_projects). test_rail_browser.py drags and hides in a browser."""

import pytest

from app.models import ProjectStatus
from app.services import DomainError
from app.services import projects as projects_svc
from app.services import rail as rail_svc


def keys(db) -> list[tuple[str, list[str]]]:
    return [(s.section.key, [m.module.key for m in s.modules]) for s in rail_svc.layout(db)]


def hidden(db) -> set[str]:
    return {m.module.key for s in rail_svc.layout(db) for m in s.modules if m.hidden}


def test_the_rail_starts_as_the_code_lists_it(db) -> None:
    assert keys(db) == [
        ("planner", ["today", "calendar"]),
        ("projects", ["projects"]),
        ("health", ["nutrition", "me", "garmin"]),
        ("finances", ["spending", "accounts", "bills", "goals"]),
        ("code", ["repositories"]),
    ]
    assert hidden(db) == set()
    assert keys(None) == keys(db)


def test_sections_and_modules_keep_the_order_they_are_dragged_to(db) -> None:
    rail_svc.save_layout(
        db,
        sections=["health", "planner", "projects", "finances", "code"],
        modules={"planner": ["calendar", "today"], "finances": ["goals", "spending"]},
        hidden=["accounts", "bills"],
    )
    db.commit()
    assert keys(db)[:2] == [
        ("health", ["nutrition", "me", "garmin"]),
        ("planner", ["calendar", "today"]),
    ]
    # Modules not named keep their places after the ones named.
    assert dict(keys(db))["finances"] == ["goals", "spending", "accounts", "bills"]
    assert hidden(db) == {"accounts", "bills"}
    finances = next(s for s in rail_svc.layout(db) if s.section.key == "finances")
    assert not finances.hidden


def numbers(db) -> dict[str, str]:
    return {m.module.key: m.number for s in rail_svc.layout(db) for m in s.modules if m.number}


def test_the_modules_showing_are_numbered_top_to_bottom_up_to_nine(db) -> None:
    assert numbers(db) == {
        "today": "1",
        "calendar": "2",
        "projects": "3",
        "nutrition": "4",
        "me": "5",
        "garmin": "6",
        "spending": "7",
        "accounts": "8",
        "bills": "9",
    }
    # A hidden module has none, and the ones after it move up.
    rail_svc.save_layout(
        db,
        sections=["code", "planner"],
        modules={"planner": ["calendar", "today"]},
        hidden=["nutrition", "me", "accounts"],
    )
    assert numbers(db) == {
        "repositories": "1",
        "calendar": "2",
        "today": "3",
        "projects": "4",
        "garmin": "5",
        "spending": "6",
        "bills": "7",
        "goals": "8",
    }


def test_a_section_with_every_module_hidden_is_hidden(db) -> None:
    rail_svc.save_layout(
        db, sections=[], modules={}, hidden=["spending", "accounts", "bills", "goals"]
    )
    finances = next(s for s in rail_svc.layout(db) if s.section.key == "finances")
    assert finances.hidden


def test_a_module_never_moves_to_another_section(db) -> None:
    with pytest.raises(DomainError, match="spending is not in projects"):
        rail_svc.save_layout(db, sections=[], modules={"projects": ["spending"]}, hidden=[])
    with pytest.raises(DomainError, match="No section"):
        rail_svc.save_layout(db, sections=["nowhere"], modules={}, hidden=[])
    with pytest.raises(DomainError, match="No module"):
        rail_svc.save_layout(db, sections=[], modules={}, hidden=["nothing"])


def test_a_layout_saved_before_a_module_existed_takes_it_in_at_its_sections_end(db) -> None:
    from app.models import Setting

    db.add(
        Setting(
            key="rail",
            value={
                "sections": ["code", "planner"],
                "modules": {"health": ["garmin"]},
                "hidden": ["gone"],
            },
        )
    )
    db.flush()
    assert [k for k, _ in keys(db)] == ["code", "planner", "projects", "health", "finances"]
    assert dict(keys(db))["health"] == ["garmin", "nutrition", "me"]
    assert hidden(db) == set()


def test_the_rail_route_keeps_the_layout_and_the_page_draws_it(client, db) -> None:
    saved = client.put(
        "/ui/rail",
        json={
            "sections": ["finances", "planner", "projects", "health", "code"],
            "modules": {"planner": ["calendar", "today"]},
            "hidden": ["accounts"],
        },
    )
    assert saved.status_code == 204
    nav = client.get("/today").text.split('<nav class="nav"')[1].split("</nav>")[0]
    sections = [part.split('"')[0] for part in nav.split('data-section="')[1:]]
    assert sections == ["finances", "planner", "projects", "health", "code"]
    assert nav.index('href="/calendar"') < nav.index('href="/today"')
    accounts = nav.split('data-module="accounts"')[1].split(">")[0]
    assert "hidden" in accounts
    # The numbers follow the places: Spending, Bills and Goals before Calendar and Today.
    assert 'href="/calendar" title="Calendar" draggable="false" aria-keyshortcuts="Alt+4"' in nav
    assert 'href="/today" title="Today" draggable="false" aria-keyshortcuts="Alt+5"' in nav
    assert '<span class="nav-key" aria-hidden="true">5</span>' in nav.split('href="/today"')[1]

    refused = client.put(
        "/ui/rail", json={"sections": [], "modules": {"code": ["today"]}, "hidden": []}
    )
    assert refused.status_code == 422


def test_projects_keep_the_order_they_are_dragged_to(client, db) -> None:
    a, b, c = (projects_svc.create_project(db, name=n) for n in ("A", "B", "C"))
    shelved = projects_svc.create_project(db, name="Shelved")
    projects_svc.update_project(db, shelved.id, status=ProjectStatus.paused)
    d = projects_svc.create_project(db, name="D")
    db.commit()
    assert [p.name for p in projects_svc.list_projects(db)] == ["A", "B", "C", "Shelved", "D"]

    # The active ones, as the sidebar lists them: they swap their places, the shelved keeps its.
    saved = client.put("/ui/projects/order", json={"ids": [d.id, a.id, c.id, b.id]})
    assert saved.status_code == 204
    assert [p.name for p in projects_svc.list_projects(db)] == ["D", "A", "C", "Shelved", "B"]
    rail = client.get("/ui/rail/projects").text
    assert [rail.index(f">{n}<") for n in "DACB"] == sorted(rail.index(f">{n}<") for n in "DACB")

    # A new project comes last.
    projects_svc.create_project(db, name="E")
    assert projects_svc.list_projects(db)[-1].name == "E"

    assert client.put("/ui/projects/order", json={"ids": [a.id, a.id]}).status_code == 422
    assert client.put("/ui/projects/order", json={"ids": [999]}).status_code == 422


def test_projects_sharing_a_place_are_spread_out_first(db) -> None:
    from app.models import Project

    for name in ("X", "Y", "Z"):
        db.add(Project(name=name))
    db.flush()
    x, y, z = projects_svc.list_projects(db)
    projects_svc.reorder_projects(db, [z.id, x.id])
    assert [p.name for p in projects_svc.list_projects(db)] == ["Z", "Y", "X"]
