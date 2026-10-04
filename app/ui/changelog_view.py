"""The Changelog as the page draws it: every version, newest first, and
what each one changed (app/changelog.py), the one running marked."""

from __future__ import annotations

from datetime import date
from typing import Any

from app import changelog
from app.markdown import render_inline, render_markdown

KIND_LABELS = {"major": "Major", "feature": "Feature", "fix": "Fix"}


def release_ctx(release: changelog.Release, running: changelog.Running) -> dict[str, Any]:
    day = release.released
    return {
        "version": release.version,
        # "4 Oct 2026": a changelog runs over years.
        "released": f"{day.day} {day:%b %Y}" if day else None,
        "kind": release.kind,
        "current": release.version is not None and release.version == running.version,
        "changes": [
            {
                "kind": c.kind,
                "label": KIND_LABELS[c.kind],
                "summary": render_inline(c.summary),
                "details": render_markdown(c.details) if c.details else "",
            }
            for c in release.changes
        ],
    }


def page_ctx(today: date) -> dict[str, Any]:
    running = changelog.running()
    return {
        "running": running,
        "releases": [release_ctx(r, running) for r in running.releases],
        "today": today,
    }
