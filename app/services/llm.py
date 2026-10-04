"""Models: the LLM providers this machine reaches (Claude through Claude
Code, OpenAI through the Codex CLI), the models each offers, and which of
them each of the app's features uses.

A check asks each provider's CLI how it stands (sources/llm.py) and keeps
the answer, so pages draw the last one at once and check again in the
background when it is old. The choices are kept as one setting: where
each CLI is, when it is not on PATH, and a model (and its reasoning effort)
for each use. A use not chosen for runs on its provider's own default.

A feature that calls a model is a Use here, naming the providers it can
run on; it asks `choice` for what to run with.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Setting
from app.services import DomainError
from app.services.syncing import Syncing
from app.sources import llm
from app.sources.llm import BY_KEY, PROVIDERS, Model, Probe, Status

log = logging.getLogger(__name__)

SETTING = "llm"
STATUS = "llm_status"
# A check older than this is made again when a page shows it.
STALE = timedelta(minutes=5)


@dataclass(frozen=True)
class Use:
    """A feature of the app that calls a model."""

    key: str
    label: str
    hint: str
    # The providers it can run on, the first its default.
    providers: tuple[str, ...]
    # The module it belongs to: not installed, it is not offered.
    module: str | None = None


# The chats run Claude Code through the Agent SDK (its tools and hooks are
# the SDK's), so Claude alone.
USES = (
    Use("nutrition", "Nutrition's chat", "Keeps the day's log from what you tell it",
        ("claude",), "health"),
    Use("money", "Spending's chat", "Sorts and budgets the month with you",
        ("claude",), "finances"),
)
_USES = {u.key: u for u in USES}

EFFORT_LABELS = {
    "none": "None", "minimal": "Minimal", "low": "Low", "medium": "Medium", "high": "High",
    "xhigh": "Extra high", "max": "Max",
}


def effort_label(effort: str) -> str:
    return EFFORT_LABELS.get(effort, effort.replace("_", " ").capitalize())


def uses() -> list[Use]:
    """The uses this machine has, as the code lists them."""
    settings = get_settings()
    return [u for u in USES if u.module is None or settings.installed(u.module)]


@dataclass(frozen=True)
class Choice:
    """What a use runs with: its provider, the model (None: the provider's
    own default), the reasoning effort (None: the model's own), and where
    the provider's CLI is ("" to find it)."""

    provider: str
    model: str | None
    effort: str | None
    cli: str


# ---- the setting ----


def _saved(db: Session, key: str) -> dict[str, Any]:
    row = db.get(Setting, key)
    return row.value if row is not None and isinstance(row.value, dict) else {}


def _save(db: Session, key: str, value: dict[str, Any]) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def cli(db: Session, provider: str) -> str:
    """Where the provider's CLI was set to be; "" to find it on PATH."""
    return str((_saved(db, SETTING).get("cli") or {}).get(provider) or "")


def set_cli(db: Session, provider: str, path: str) -> None:
    """Where the provider's CLI is, or "" to find it on PATH again."""
    if provider not in BY_KEY:
        raise DomainError(f"No provider {provider}")
    path = path.strip().strip('"').strip()
    if path and not Path(path).is_file():
        raise DomainError(f"There is no file at {path}")
    saved = _saved(db, SETTING)
    _save(db, SETTING, {**saved, "cli": {**(saved.get("cli") or {}), provider: path}})


def choice(db: Session, use: str) -> Choice:
    """What the use runs with: as chosen, else its first provider's default."""
    found = _USES[use]
    saved = (_saved(db, SETTING).get("uses") or {}).get(use) or {}
    provider = saved.get("provider")
    if provider not in found.providers:
        provider, saved = found.providers[0], {}
    model, effort = saved.get("model") or None, saved.get("effort") or None
    return Choice(provider, model, effort, cli(db, provider))


def choose(db: Session, use: str, provider: str, model: str = "", effort: str = "") -> None:
    """The model a use runs with ("" for its provider's default), and its
    effort ("" for the model's own), checked against the provider's models
    as last listed. An effort the model does not take is let go."""
    found = _USES.get(use)
    if found is None:
        raise DomainError(f"No use {use}")
    if provider not in found.providers:
        name = BY_KEY[provider].name if provider in BY_KEY else provider
        raise DomainError(f"{found.label} cannot run on {name}")
    listed = status(db, provider)
    offered: Model | None = None
    if model and listed is not None and listed.models:
        offered = listed.model(model)
        if offered is None:
            raise DomainError(f"{BY_KEY[provider].program} does not offer {model}")
    if model == "" and listed is not None:
        offered = listed.default_model
    if effort and offered is not None and effort not in offered.efforts:
        effort = ""
    saved = _saved(db, SETTING)
    chosen = {"provider": provider, "model": model, "effort": effort}
    _save(db, SETTING, {**saved, "uses": {**(saved.get("uses") or {}), use: chosen}})


# ---- the providers, as last checked ----


def statuses(db: Session) -> dict[str, Status | None]:
    """Each provider as last checked, None when it never was."""
    saved = _saved(db, STATUS)
    found: dict[str, Status | None] = {}
    for provider in PROVIDERS:
        data = saved.get(provider.key)
        try:
            found[provider.key] = Status.from_dict(data) if isinstance(data, dict) else None
        except (KeyError, TypeError, ValueError):
            log.warning("Unreadable status kept for %s", provider.key)
            found[provider.key] = None
    return found


def status(db: Session, provider: str) -> Status | None:
    return statuses(db).get(provider)


def stale(db: Session, now: datetime | None = None) -> bool:
    """Whether a provider was never checked, or not lately."""
    now = now or datetime.now()
    return any(s is None or now - s.checked_at > STALE for s in statuses(db).values())


def keep(db: Session, found: list[Status]) -> None:
    saved = _saved(db, STATUS)
    _save(db, STATUS, {**saved, **{s.provider: s.to_dict() for s in found}})


checking = Syncing("llm-check")


def check(db: Session, probe: Probe = llm.probe) -> list[Status]:
    """Ask every provider how it stands, at once, and keep the answers."""
    wanted = [(p.key, cli(db, p.key)) for p in PROVIDERS]
    with ThreadPoolExecutor(max_workers=len(wanted), thread_name_prefix="llm-probe") as pool:
        found = list(pool.map(lambda args: probe(*args), wanted))
    keep(db, found)
    return found


def run_check(factory: Callable[[], Session], probe: Probe = llm.probe) -> None:
    """A whole check in its own session, committed at its end: for a thread."""
    with factory() as db:
        try:
            for s in check(db, probe):
                log.info("%s: %s %s", s.provider, s.state, s.message)
        except Exception:
            log.exception("Checking the model providers crashed")
            db.rollback()
            return
        db.commit()
