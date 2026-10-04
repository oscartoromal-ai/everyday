"""The sidebar's layout: its sections (Planner, Projects, Health, Finances,
Code) and the modules (pages) in each, in the order Oscar dragged them, and
the modules he hid. Kept as the "rail" setting, so it holds on every device;
a module or section the code adds later joins at its section's end. A section
the machine was installed without (Health, Finances, Code) is left out. The
modules showing are numbered top to bottom, for Alt+1 to Alt+9."""

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
            Module("today", "Today", "/today"),
            Module("calendar", "Calendar", "/calendar"),
        ),
    ),
    Section("projects", None, (Module("projects", "Projects", "/projects"),)),
    Section(
        "health",
        "Health",
        (
            Module("nutrition", "Nutrition", "/nutrition"),
            Module("me", "Me", "/me"),
            Module("garmin", "Garmin", "/garmin"),
        ),
    ),
    Section(
        "finances",
        "Finances",
        (
            Module("spending", "Spending", "/spending"),
            Module("accounts", "Accounts", "/accounts"),
            Module("bills", "Bills", "/bills"),
            Module("goals", "Goals", "/goals"),
        ),
    ),
    Section("code", "Code", (Module("repositories", "Repositories", "/repositories"),)),
)
_SECTIONS = {s.key: s for s in SECTIONS}


# Alt+1 to Alt+9: the modules showing, top to bottom, hidden ones skipped.
KEYS = 9


@dataclass(frozen=True)
class PlacedModule:
    module: Module
    hidden: bool
    # Its number on the keyboard (Alt+number), "" when hidden or past the ninth.
    number: str = ""


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


def layout(db: Session | None) -> list[PlacedSection]:
    """The sections installed in their order, each with its modules in
    theirs; as the code lists them with no session to read the setting from."""
    setting = None if db is None else db.get(Setting, SETTING)
    saved = setting.value if setting and isinstance(setting.value, dict) else {}
    hidden = set(saved.get("hidden", []))
    modules = saved.get("modules", {})
    settings = get_settings()
    placed = []
    shown = 0
    for section_key in _ordered(saved.get("sections", []), list(_SECTIONS)):
        if not settings.installed(section_key):
            continue
        section = _SECTIONS[section_key]
        by_key = {m.key: m for m in section.modules}
        items = []
        for k in _ordered(modules.get(section_key, []), list(by_key)):
            number = ""
            if k not in hidden:
                shown += 1
                number = str(shown) if shown <= KEYS else ""
            items.append(PlacedModule(by_key[k], k in hidden, number))
        placed.append(PlacedSection(section, tuple(items)))
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
