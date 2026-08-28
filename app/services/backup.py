"""Daily backup snapshots via SQLite's backup API (SPEC.md section 8).

Runs on a fresh sqlite3 connection to the settings db_path (not the process
engine), writing a dated snapshot into the configured backup dir and pruning
to the newest `retain` files. Restore is a file copy: stop the app, copy a
snapshot back over data/personal-calendar.db.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

SNAPSHOT_PREFIX = "personal-calendar-"
SNAPSHOT_SUFFIX = ".db"


def snapshot_path(backup_dir: Path, today: date) -> Path:
    return backup_dir / f"{SNAPSHOT_PREFIX}{today.isoformat()}{SNAPSHOT_SUFFIX}"


def run_backup(db_path: Path, backup_dir: Path, retain: int, today: date | None = None) -> Path:
    """Write a dated snapshot of db_path into backup_dir and prune old ones."""
    today = today or date.today()
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest_path = snapshot_path(backup_dir, today)

    source = sqlite3.connect(db_path)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    prune_snapshots(backup_dir, retain)
    return dest_path


def prune_snapshots(backup_dir: Path, retain: int) -> list[Path]:
    """Delete the oldest snapshots beyond `retain`; returns the deleted paths."""
    snapshots = sorted(backup_dir.glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_SUFFIX}"))
    excess = len(snapshots) - retain
    if excess <= 0:
        return []
    to_delete = snapshots[:excess]
    for path in to_delete:
        path.unlink()
    return to_delete
