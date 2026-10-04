"""The sidebar's layout: its sections (Planner, Projects, Health, Finances,
Code) and the modules (pages) in each, in the order Oscar dragged them, and
the modules he hid. Kept as the "rail" setting, so it holds on every device;
a module or section the code adds later joins at its section's end. A section
the machine was installed without (Health, Finances, Code) is left out."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Setting
from app.services import DomainError

SETTING = "rail"


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    href: str
    # Its key on the keyboard (1 to 9), the same wherever it is dragged.
    shortcut: str = ""


@dataclass(frozen=True)
class Section:
    key: str
    # None for a section whose one module heads it (Projects, its projects under it).
    label: str | None
    modules: tuple[Module, ...]


SECTIONS: tuple[Section, ...] = (
    Section(
        "planner",
        "Planner",
        (
            Module("today", "Today", "/today", "1"),
            Module("calendar", "Calendar", "/calendar", "2"),
        ),
    ),
    Section("projects", None, (Module("projects", "Projects", "/projects", "3"),)),
    Section(
        "health",
        "Health",
        (
            Module("nutrition", "Nutrition", "/nutrition", "4"),
            Module("me", "Me", "/me", "5"),
            Module("garmin", "Garmin", "/garmin", "6"),
        ),
    ),
    Section(
        "finances",
        "Finances",
        (
            Module("spending", "Spending", "/spending", "7"),
            Module("accounts", "Accounts", "/accounts"),
            Module("bills", "Bills", "/bills"),
            Module("goals", "Goals", "/goals"),
        ),
    ),
    Section("code", "Code", (Module("repositories", "Repositories", "/repositories", "8"),)),
)
_SECTIONS = {s.key: s for s in SECTIONS}


@dataclass(frozen=True)
class PlacedModule:
    module: Module
    hidden: bool


@dataclass(frozen=True)
class PlacedSection:
    section: Section
    modules: tuple[PlacedModule, ...]

    @property
    def hidden(self) -> bool:
        """Every module in it hidden: the section goes too."""
        return all(m.hidden for m in self.modules)


def _ordered(keys: list[str], known: list[str]) -> list[str]:
    """The known keys in the order given; the ones not given after, as known."""
    given = [k for k in dict.fromkeys(keys) if k in known]
    return given + [k for k in known if k not in given]


def not_installed() -> list[Section]:
    """The sections this machine was installed without, as the code lists them."""
    settings = get_settings()
    return [s for s in SECTIONS if not settings.installed(s.key)]


def keyed() -> list[Module]:
    """The installed modules with a key, by their key."""
    settings = get_settings()
    modules = [m for s in SECTIONS if settings.installed(s.key) for m in s.modules]
    return sorted((m for m in modules if m.shortcut), key=lambda m: m.shortcut)


def key_runs(modules: list[Module]) -> list[tuple[str, str]]:
    """Their keys as runs, first and last: 1 to 6 and 8 without Spending's 7."""
    runs: list[list[str]] = []
    for m in modules:
        if runs and int(m.shortcut) == int(runs[-1][1]) + 1:
            runs[-1][1] = m.shortcut
        else:
            runs.append([m.shortcut, m.shortcut])
    return [(first, last) for first, last in runs]


def layout(db: Session | None) -> list[PlacedSection]:
    """The sections installed in their order, each with its modules in
    theirs; as the code lists them with no session to read the setting from."""
    setting = None if db is None else db.get(Setting, SETTING)
    saved = setting.value if setting and isinstance(setting.value, dict) else {}
    hidden = set(saved.get("hidden", []))
    modules = saved.get("modules", {})
    settings = get_settings()
    placed = []
    for section_key in _ordered(saved.get("sections", []), list(_SECTIONS)):
        if not settings.installed(section_key):
            continue
        section = _SECTIONS[section_key]
        by_key = {m.key: m for m in section.modules}
        order = _ordered(modules.get(section_key, []), list(by_key))
        placed.append(
            PlacedSection(section, tuple(PlacedModule(by_key[k], k in hidden) for k in order))
        )
    return placed


def save_layout(
    db: Session, *, sections: list[str], modules: dict[str, list[str]], hidden: list[str]
) -> None:
    """The order of the sections, of the modules in each, and the modules
    hidden. A module only ever moves within its own section."""
    for key in sections:
        if key not in _SECTIONS:
            raise DomainError(f"No section {key}")
    for section_key, keys in modules.items():
        section = _SECTIONS.get(section_key)
        if section is None:
            raise DomainError(f"No section {section_key}")
        own = {m.key for m in section.modules}
        for key in keys:
            if key not in own:
                raise DomainError(f"{key} is not in {section_key}")
    every = {m.key for s in SECTIONS for m in s.modules}
    for key in hidden:
        if key not in every:
            raise DomainError(f"No module {key}")
    value = {
        "sections": _ordered(sections, list(_SECTIONS)),
        "modules": {
            s.key: _ordered(modules.get(s.key, []), [m.key for m in s.modules]) for s in SECTIONS
        },
        "hidden": sorted(set(hidden)),
    }
    setting = db.get(Setting, SETTING)
    if setting is None:
        db.add(Setting(key=SETTING, value=value))
    else:
        setting.value = value
    db.flush()
