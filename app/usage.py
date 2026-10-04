"""How the app is used: each request counted against its route and day (RouteUse).

A request is counted by the route that answered it ("GET /projects/{project_id}",
"POST /mcp"), never by the address asked for, with whether it failed (a 5xx,
or an error no response came from) and how long its response took to start
(a streamed answer is as quick as its first word). Static files and addresses
no route answers are not counted.

The counts gather in memory and a background job writes them to the database
every minute, and once more as the app stops, so no request waits on a write.
The daily scan for what to improve (improve/) reads them: which pages are used
most, which fail, which are slow.

Raw ASGI middleware, as app/security.py's: BaseHTTPMiddleware would buffer
the MCP streaming mount.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.models import RouteUse

UNCOUNTED_MOUNTS = ("/static",)


@dataclass
class _Count:
    requests: int = 0
    failures: int = 0
    total_ms: int = 0
    slowest_ms: int = 0

    def add(self, other: _Count) -> None:
        self.requests += other.requests
        self.failures += other.failures
        self.total_ms += other.total_ms
        self.slowest_ms = max(self.slowest_ms, other.slowest_ms)


class UsageRecorder:
    """The counts not yet written, by day and route."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[date, str], _Count] = {}

    def record(self, route: str, ms: int, failed: bool, day: date | None = None) -> None:
        count = _Count(1, int(failed), ms, ms)
        with self._lock:
            self._counts.setdefault((day or date.today(), route), _Count()).add(count)

    def flush(self, db: Session) -> int:
        """The counts gathered added to the database's; how many routes they
        were for. Kept for the next flush should the write fail."""
        with self._lock:
            counts, self._counts = self._counts, {}
        if not counts:
            return 0
        rows = [
            {"day": day, "route": route, **vars(count)} for (day, route), count in counts.items()
        ]
        stmt = insert(RouteUse).values(rows)
        new = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[RouteUse.day, RouteUse.route],
            set_={
                "requests": RouteUse.requests + new.requests,
                "failures": RouteUse.failures + new.failures,
                "total_ms": RouteUse.total_ms + new.total_ms,
                # SQLite's max() of two values, the larger.
                "slowest_ms": func.max(RouteUse.slowest_ms, new.slowest_ms),
            },
        )
        try:
            db.execute(stmt)
            db.flush()
        except Exception:
            with self._lock:
                for key, count in counts.items():
                    self._counts.setdefault(key, _Count()).add(count)
            raise
        return len(rows)


# The app's one recorder: the middleware counts into it, the job flushes it.
recorder = UsageRecorder()


def route_of(scope: dict, root_path: str) -> str | None:
    """The route that answered a request ("GET /tasks/{task_id}"), or the
    mount ("POST /mcp"); None for one not counted."""
    path = getattr(scope.get("route"), "path", None)
    if path is None:
        # A mount adds its path to the root path (Starlette's Mount).
        mounted = scope.get("root_path", "")
        if mounted != root_path:
            path = mounted[len(root_path) :]
    if path is None or path.startswith(UNCOUNTED_MOUNTS):
        return None
    return f"{scope['method']} {path}"


class UsageMiddleware:
    def __init__(self, app, recorder: UsageRecorder | None = None) -> None:  # noqa: ANN001
        self.app = app
        # None: the app's one, as it is when a request comes.
        self.recorder = recorder

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        root_path = scope.get("root_path", "")
        started = time.perf_counter()
        response: dict = {}

        async def send_timed(message) -> None:  # noqa: ANN001
            if message["type"] == "http.response.start":
                response["status"] = message["status"]
                response["ms"] = round((time.perf_counter() - started) * 1000)
            await send(message)

        # An error raised fails the request, even one whose response had started.
        raised = True
        try:
            await self.app(scope, receive, send_timed)
            raised = False
        finally:
            route = route_of(scope, root_path)
            if route is not None:
                ms = response.get("ms", round((time.perf_counter() - started) * 1000))
                failed = raised or response.get("status", 500) >= 500
                (self.recorder or recorder).record(route, ms, failed)
