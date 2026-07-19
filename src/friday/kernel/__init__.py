"""Friday enforcement kernel (implementation-spec §8).

The kernel is where role/information boundaries are enforced in code, not
prompt. Mode selects the policy (validate = information asymmetry, collaborate
= role asymmetry); Authority enforces the non-negotiable judgment power (GPT can
never halt/redesign/verdict); the integrity asserts (re-exported) enforce the
filesystem boundaries.
"""

from .mode import Mode
from .authority import Authority
from .. import integrity  # noqa: F401  (re-export the assert module)

__all__ = ["Mode", "Authority", "integrity"]
