"""The database brought up to the code's schema as the app starts.

The installed app creates its database on first run and migrates it on each
start after an update, so installing or upgrading is the whole of it. The
migrations are the repo's Alembic ones (migrations/, shipped inside the
installed app), run in-process, all of an upgrade in one transaction with
foreign keys off (migrations/env.py, app/db.py's make_migration_engine).

A database is copied before it is migrated (copies(), the newest KEPT kept),
and the migration stays unconfirmed until the version that made it has come
up on it (confirm). A version that fails to come up after migrating puts the
database back as it was (go_back), and so does the version before it, should
it start on a database migrated by one that never came up: rather than
refuse a database it cannot read, which would leave the app unable to start
until the database was put back by hand.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.config import REPO_ROOT
from app.db import make_engine

log = logging.getLogger(__name__)

# The copies kept from before migrating, the newest.
KEPT = 5


class DatabaseTooNew(RuntimeError):
    """The database was migrated by a newer version of the app than this one."""


def _config(db_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    # Read by migrations/env.py; percent signs are ConfigParser interpolation.
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}".replace("%", "%%"))
    return config


def current_revisions(db_path: Path) -> set[str]:
    engine = make_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            return set(MigrationContext.configure(connection).get_current_heads())
    finally:
        engine.dispose()


def copies(db_path: Path) -> Path:
    """Where the database's copies from before migrating are kept."""
    return db_path.parent / "before-migrating"


def _unconfirmed(db_path: Path) -> Path:
    """Says which copy a migration not yet confirmed was made from."""
    return copies(db_path) / "unconfirmed.json"


def upgrade(db_path: Path) -> None:
    """Create the database at `db_path`, or migrate it to the code's head.
    Raises DatabaseTooNew rather than touch a database from a newer app,
    unless that app never came up on what it migrated (go_back)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config = _config(db_path)
    script = ScriptDirectory.from_config(config)
    known = {rev.revision for rev in script.walk_revisions()}
    current = current_revisions(db_path)
    if current - known:
        if not go_back(db_path, known):
            raise DatabaseTooNew(
                f"{db_path} is at revision {', '.join(sorted(current - known))}, "
                "newer than this version of the app knows"
            )
        current = current_revisions(db_path)
    heads = set(script.get_heads())
    if current == heads:
        return
    copy = _keep(db_path, current, heads) if current else None
    log.info("Migrating %s from %s", db_path, ", ".join(sorted(current)) or "empty")
    try:
        command.upgrade(config, "head")
    except BaseException:
        # Undone whole (one transaction): the database is as its copy has
        # it, and there is nothing to confirm or go back on.
        _unconfirmed(db_path).unlink(missing_ok=True)
        if copy is not None:
            copy.unlink(missing_ok=True)
        raise
    for old in sorted(copies(db_path).glob(f"{db_path.stem}-*.db"))[:-KEPT]:
        old.unlink(missing_ok=True)


def _keep(db_path: Path, current: set[str], heads: set[str]) -> Path:
    """The database copied as it is, before it is migrated from `current` to
    `heads`, and that migration noted unconfirmed. The copy."""
    folder = copies(db_path)
    folder.mkdir(parents=True, exist_ok=True)
    made = datetime.now()
    copy = folder / f"{db_path.stem}-{made:%Y-%m-%d-%H%M%S}-{'-'.join(sorted(current))}.db"
    _copy(db_path, copy)
    _unconfirmed(db_path).write_text(
        json.dumps({"copy": copy.name, "from": sorted(current), "to": sorted(heads)}),
        encoding="utf-8",
    )
    log.info("Copied %s to %s before migrating it", db_path, copy)
    return copy


def confirm(db_path: Path) -> None:
    """The app came up on its database: a migration it made is for good,
    never gone back on."""
    _unconfirmed(db_path).unlink(missing_ok=True)


def go_back(db_path: Path, known: set[str] | None = None) -> bool:
    """The database put back as it was before a migration that the version
    which made it never came up on, from the copy made first, while it is
    still as that migration left it; whether it was. With `known`, the
    revisions of the code going back: only to a copy it can read."""
    marker = _unconfirmed(db_path)
    try:
        unconfirmed = json.loads(marker.read_text(encoding="utf-8"))
        copy = copies(db_path) / unconfirmed["copy"]
        before, after = set(unconfirmed["from"]), set(unconfirmed["to"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not copy.exists() or current_revisions(db_path) != after:
        return False
    if known is not None and not before <= known:
        return False
    log.warning(
        "%s was migrated from %s by a version that never came up on it: put back as it "
        "was, from %s (anything written since is gone)",
        db_path,
        ", ".join(sorted(before)),
        copy,
    )
    _copy(copy, db_path)
    marker.unlink(missing_ok=True)
    return True


def _copy(source: Path, target: Path) -> None:
    """`source` copied over `target` through SQLite's backup API: whole,
    with what is still in its write-ahead log, even while it is open."""
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
