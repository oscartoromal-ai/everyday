"""Browser-side hardening (SPEC.md section 8).

Network boundary is the trust boundary (localhost + tailnet, no login), so the
job here is keeping *browsers* honest: reject requests whose Host or Origin is
not the app's own (DNS rebinding, cross-site XHR against localhost), and
require a double-submit CSRF token on unsafe browser-path requests.

Raw ASGI middleware: BaseHTTPMiddleware would buffer the MCP streaming mount.
"""

from __future__ import annotations

import secrets
from http import cookies as http_cookies
from urllib.parse import urlsplit

CSRF_COOKIE = "csrf"
CSRF_HEADER = b"x-csrf"
# Browser-facing unsafe paths that need the CSRF check; /mcp is cookie-less.
CSRF_PATH_PREFIXES = ("/ui", "/api")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _header(scope, name: bytes) -> str | None:  # noqa: ANN001
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def _hostname(netloc_or_host: str) -> str:
    host = netloc_or_host.rsplit(":", 1)[0] if ":" in netloc_or_host else netloc_or_host
    return host.strip("[]").lower()


class BrowserGuardMiddleware:
    def __init__(self, app, allowed_hosts: set[str]) -> None:  # noqa: ANN001
        self.app = app
        self.allowed_hosts = {h.lower() for h in allowed_hosts}

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host = _header(scope, b"host")
        if host is None or _hostname(host) not in self.allowed_hosts:
            await self._reject(send, 421, "Unrecognized Host header")
            return

        method = scope["method"].upper()
        origin = _header(scope, b"origin")
        if (
            method in UNSAFE_METHODS
            and origin
            and origin != "null"
            and _hostname(urlsplit(origin).netloc) not in self.allowed_hosts
        ):
            await self._reject(send, 403, "Cross-origin request rejected")
            return

        path = scope["path"]
        needs_csrf = method in UNSAFE_METHODS and path.startswith(CSRF_PATH_PREFIXES)
        if needs_csrf:
            cookie_token = self._cookie_token(scope)
            header_token = _header(scope, CSRF_HEADER)
            if not cookie_token or header_token != cookie_token:
                await self._reject(send, 403, "Missing or invalid CSRF token")
                return

        # Ensure the double-submit cookie exists (readable by page JS).
        if self._cookie_token(scope) is None and method == "GET":
            token = secrets.token_urlsafe(32)

            async def send_with_cookie(message) -> None:  # noqa: ANN001
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append(
                        (
                            b"set-cookie",
                            f"{CSRF_COOKIE}={token}; Path=/; SameSite=Strict".encode(),
                        )
                    )
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_cookie)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _cookie_token(scope) -> str | None:  # noqa: ANN001
        raw = _header(scope, b"cookie")
        if not raw:
            return None
        jar = http_cookies.SimpleCookie()
        try:
            jar.load(raw)
        except http_cookies.CookieError:
            return None
        morsel = jar.get(CSRF_COOKIE)
        return morsel.value if morsel else None

    @staticmethod
    async def _reject(send, status: int, message: str) -> None:  # noqa: ANN001
        body = message.encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
