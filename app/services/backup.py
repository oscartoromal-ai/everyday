"""Daily backup snapshots via SQLite's backup API (SPEC.md section 8), and
of the everyday files, zipped (SPEC.md, Files first).

Runs on a fresh sqlite3 connection to the settings db_path (not the process
engine), writing a dated snapshot into the configured backup dir and pruning
to the newest `retain` files. Restore is a file copy: stop the app, copy a
snapshot back over data/personal-calendar.db.

The everyday files' zip beside it holds what the planner writes there
(projects/, tasks/, notebook/, README.md), not the clones in repos/ nor the
checkouts in work/; restore is unzipping it over the folder, the app quit.
"""

from __future__ import annotations

import os
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

SNAPSHOT_PREFIX = "personal-calendar-"
SNAPSHOT_SUFFIX = ".db"
FILES_PREFIX = "everyday-files-"
FILES_SUFFIX = ".zip"
# What of the everyday files a backup leaves out: clones and checkouts,
# which their repositories keep.
LEFT_OUT = {"repos", "work"}


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


def files_path(backup_dir: Path, today: date) -> Path:
    return backup_dir / f"{FILES_PREFIX}{today.isoformat()}{FILES_SUFFIX}"


def run_files_backup(
    root: Path, backup_dir: Path, retain: int, today: date | None = None
) -> Path | None:
    """Zip the everyday files (but repos/ and work/) into backup_dir, dated,
    and prune old zips; None when there is no folder to back up."""
    if not root.is_dir():
        return None
    today = today or date.today()
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = files_path(backup_dir, today)
    partial = dest.with_name(dest.name + ".partial")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zipped:
        for here, subdirs, names in os.walk(root):
            base = Path(here)
            if base == root:
                subdirs[:] = [d for d in subdirs if d not in LEFT_OUT]
            for name in names:
                path = base / name
                try:
                    zipped.write(path, path.relative_to(root).as_posix())
                except OSError:
                    continue  # a file going as it was read
    os.replace(partial, dest)
    zips = sorted(backup_dir.glob(f"{FILES_PREFIX}*{FILES_SUFFIX}"))
    for old in zips[: max(0, len(zips) - retain)]:
        old.unlink()
    return dest
