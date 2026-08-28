class DomainError(ValueError):
    """A domain rule was violated; maps to HTTP 422 / MCP tool error."""
