"""The ledger: every finding the scan has met, kept across days (ledger.json).

An entry's status says what is being done about its finding:

- open: nothing yet; the pick may take it.
- picked: taken on, by an agent or by hand, with its pull request once there
  is one; never picked again while it is.
- done: fixed, its pull request merged. Met again after that, it opens again
  (the fix did not hold).
- ignored: Oscar's call that it is not worth fixing; never picked.

An open finding not met for STALE_DAYS is no longer picked: an error that
stopped happening, a test that has passed since.

`python -m improve.ledger` lists the entries; `... mark <fingerprint> <status>`
sets one's status (with --pr, --note).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from improve import live_home
from improve.findings import KINDS, Finding

STATUSES = ("open", "picked", "done", "ignored")
STALE_DAYS = 14


@dataclass
class Entry:
    fingerprint: str
    kind: str
    key: str
    title: str
    # The latest evidence met, for the brief.
    evidence: str
    first_seen: str
    last_seen: str
    status: str = "open"
    # The day the status was set.
    since: str = ""
    # How many scans met it, and how many times it happened over them.
    scans: int = 0
    occurrences: int = 0
    # How many times it came back after being done.
    reopened: int = 0
    pr: str = ""
    note: str = ""

    @property
    def rank(self) -> int:
        return KINDS.index(self.kind)


@dataclass
class Ledger:
    path: Path
    entries: dict[str, Entry] = field(default_factory=dict)
    # When the last scan ran: the log is read from there on.
    last_scan: datetime | None = None

    @classmethod
    def load(cls, path: Path) -> Ledger:
        if not path.exists():
            return cls(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        last = data.get("last_scan")
        return cls(
            path,
            {e["fingerprint"]: Entry(**e) for e in data.get("entries", [])},
            datetime.fromisoformat(last) if last else None,
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_scan": self.last_scan.isoformat(timespec="seconds") if self.last_scan else None,
            "entries": [asdict(e) for e in self.entries.values()],
        }
        # Whole or not at all, should the scan be stopped as it writes.
        staging = self.path.with_suffix(".tmp")
        staging.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(staging, self.path)

    def meet(self, findings: list[Finding], today: date) -> list[Entry]:
        """The scan's findings entered; the entries new or come back."""
        news = []
        for finding in findings:
            entry = self.entries.get(finding.fingerprint)
            if entry is None:
                entry = self.entries[finding.fingerprint] = Entry(
                    finding.fingerprint,
                    finding.kind,
                    finding.key,
                    finding.title,
                    finding.evidence,
                    today.isoformat(),
                    today.isoformat(),
                    since=today.isoformat(),
                )
                news.append(entry)
            elif entry.status == "done":
                entry.status, entry.since = "open", today.isoformat()
                entry.reopened += 1
                news.append(entry)
            entry.title, entry.evidence = finding.title, finding.evidence
            entry.last_seen = today.isoformat()
            entry.scans += 1
            entry.occurrences += finding.occurrences
        return news

    def candidates(self, today: date) -> list[Entry]:
        """The entries the pick may take, the one it takes first: the most
        pressing kind, then the one happening most, then the oldest."""
        fresh = (today - timedelta(days=STALE_DAYS)).isoformat()
        open_ = [e for e in self.entries.values() if e.status == "open" and e.last_seen >= fresh]
        return sorted(open_, key=lambda e: (e.rank, -e.occurrences, e.first_seen))

    def mark(
        self, fingerprint: str, status: str, today: date, pr: str = "", note: str = ""
    ) -> Entry:
        if status not in STATUSES:
            raise ValueError(f"no status {status!r}; one of {', '.join(STATUSES)}")
        entry = self.entries[fingerprint]
        entry.status, entry.since = status, today.isoformat()
        entry.pr = pr or entry.pr
        entry.note = note or entry.note
        return entry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m improve.ledger", description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=live_home() / "data" / "improve",
        help="the scan's folder, holding ledger.json (the live app's)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="the entries, the next to pick first")
    mark = commands.add_parser("mark", help="set an entry's status")
    mark.add_argument("fingerprint")
    mark.add_argument("status", choices=STATUSES)
    mark.add_argument("--pr", default="")
    mark.add_argument("--note", default="")
    args = parser.parse_args(argv)

    ledger = Ledger.load(args.dir / "ledger.json")
    if args.command == "mark":
        entry = ledger.mark(args.fingerprint, args.status, date.today(), args.pr, args.note)
        ledger.save()
        print(f"{entry.fingerprint} {entry.status}: {entry.title}")
        return
    entries = sorted(
        ledger.entries.values(), key=lambda e: (STATUSES.index(e.status), e.rank, -e.occurrences)
    )
    for e in entries:
        print(f"{e.status:8} {e.fingerprint:34} x{e.occurrences:<4} {e.title}")


if __name__ == "__main__":
    main()
