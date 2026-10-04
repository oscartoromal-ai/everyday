"""Pages drawn afresh, never from a cache.

Back (the rail's arrow, Alt+Left, a page's own "‹" link) goes to the page
before as it is now, put back where it was left (shell.js), not as it was
first drawn: a task written on its own page shows written on the Gantt it
was opened from. So no HTML the app serves is kept, in the browser's cache
or its back-forward cache.

Raw ASGI middleware, as app/security.py's: BaseHTTPMiddleware would buffer
the MCP streaming mount.
"""

from __future__ import annotations


class FreshPagesMiddleware:
    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_fresh(message) -> None:  # noqa: ANN001
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {name.lower() for name, _ in headers}
                html = any(
                    name.lower() == b"content-type" and value.startswith(b"text/html")
                    for name, value in headers
                )
                if html and b"cache-control" not in names:
                    headers.append((b"cache-control", b"no-store"))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_fresh)
