"""Friday exception hierarchy (implementation-spec §15).

IntegrityBreach predates this module and is deliberately an AssertionError
subclass (existing code and tests catch it as such); it is re-exported here for
discoverability but is not reparented, to avoid changing its catch semantics.
"""

from .integrity import IntegrityBreach  # noqa: F401  (re-export; canonical def stays in integrity.py)


class FridayError(Exception):
    """Base for Friday-specific errors introduced by the collaborate system."""


class AuthorityBreach(FridayError):
    """A non-negotiable judgment action (halt/redesign/verdict) was attempted
    without human authority in its origin (spec §8, D2/D5)."""


class AdapterError(FridayError):
    """A provider CLI was unavailable, unauthenticated, or failed (spec §11)."""


class ConfigError(FridayError):
    """Invalid or unsupported configuration (spec §10)."""
