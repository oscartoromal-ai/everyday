class DomainError(ValueError):
    """A domain rule was violated; maps to HTTP 422 / MCP tool error."""


# Every session records task history; see history.py.
from app.services import history as _history  # noqa: E402, F401
