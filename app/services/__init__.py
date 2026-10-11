class DomainError(ValueError):
    """A domain rule was violated; maps to HTTP 422 / MCP tool error."""


# Every session records task history; see history.py.
from app.services import history as _history  # noqa: E402, F401

# Every commit writes the files of what it changed; see settling.py.
from app.services import settling as _settling  # noqa: E402, F401
