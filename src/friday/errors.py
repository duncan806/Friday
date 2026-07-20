"""Friday exception hierarchy."""


class FridayError(Exception):
    """Base for Friday-specific errors."""


class AdapterError(FridayError):
    """A provider CLI was unavailable, unauthenticated, or failed."""
