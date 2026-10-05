"""The app improving itself: a daily scan for what to improve, and its ledger.

Every day the app (app/jobs/improve.py) runs `python -m improve.scan` from a
checkout of origin's master. It gathers what says the app could be better,
each a finding (findings.py) from a source (sources.py): errors in the live
app's log, routes failing or slow in its use (app/usage.py), tests failing,
flaky or slow, lint, vulnerable or outdated dependencies, and the tasks Oscar
gave Claude on the app's project. The ledger (ledger.py) remembers each
finding across days, so one is told apart from yesterday's, picked once and
never again while it waits on a pull request. The scan picks one, and writes
the day's report and a brief for an agent to fix it. `python -m improve.check`
is the gate a fix passes before its pull request: lint and tests green.

All of it is scripted; an agent is needed only for the fix itself.
"""

from __future__ import annotations

import os
from pathlib import Path


def live_home() -> Path:
    """The installed app's home, where its data is (app/config.py's)."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Personal Calendar"
