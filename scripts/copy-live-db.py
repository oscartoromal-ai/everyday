"""Copy the desktop app's live database over the repo's (data/), the one a
dev server or a test run from the repo opens, to work on real data without
touching it.

    uv run python scripts/copy-live-db.py

The copy goes through SQLite's backup API, so it holds every write the
running app has made, even those still in its WAL file. The repo's database
is then migrated by the next run from the repo, not by this.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE = Path(os.environ["LOCALAPPDATA"]) / "Personal Calendar" / "data" / "personal-calendar.db"
DEV = REPO / "data" / "personal-calendar.db"


def main() -> None:
    if not LIVE.exists():
        raise SystemExit(f"No live database at {LIVE}: is the desktop app installed?")
    DEV.parent.mkdir(exist_ok=True)
    source, target = sqlite3.connect(LIVE), sqlite3.connect(DEV)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    print(f"Copied {LIVE} to {DEV}")


if __name__ == "__main__":
    main()
