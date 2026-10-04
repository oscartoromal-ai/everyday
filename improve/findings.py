"""A finding: something the scan says could be better, and what shows it."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# The kinds of finding, the most pressing first: the order picks follow.
KINDS = (
    "failing-test",  # red on master
    "error",  # logged by the live app
    "failing-route",  # answered with a 5xx in the live app
    "vulnerable-dependency",
    "flaky-test",
    "lint",
    "task",  # given to Claude on the app's project
    "slow-route",
    "slow-tests",
    "outdated-dependency",
)


@dataclass
class Finding:
    kind: str
    # What it is, the same from one scan to the next ("tests/test_api.py::test_x").
    key: str
    title: str
    # What shows it, in Markdown: the traceback, the test's output, the counts.
    evidence: str
    # How many times it happened since the last scan (an error), or 1.
    occurrences: int = 1

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:12]
        return f"{self.kind}:{digest}"

    @property
    def rank(self) -> int:
        return KINDS.index(self.kind)
