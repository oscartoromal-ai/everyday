"""The database brought up to the code's schema as the app starts.

The installed app creates its database on first run and migrates it on each
start after an update, so installing or upgrading is the whole of it. The
migrations are the repo's Alembic ones (migrations/, shipped inside the
installed app), run in-process.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.config import REPO_ROOT
from app.db import make_engine

log = logging.getLogger(__name__)


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


def upgrade(db_path: Path) -> None:
    """Create the database at `db_path`, or migrate it to the code's head.
    Raises DatabaseTooNew rather than touch a database from a newer app."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config = _config(db_path)
    script = ScriptDirectory.from_config(config)
    known = {rev.revision for rev in script.walk_revisions()}
    current = current_revisions(db_path)
    if current - known:
        raise DatabaseTooNew(
            f"{db_path} is at revision {', '.join(sorted(current - known))}, "
            "newer than this version of the app knows"
        )
    if current == set(script.get_heads()):
        return
    log.info("Migrating %s from %s", db_path, ", ".join(sorted(current)) or "empty")
    command.upgrade(config, "head")
