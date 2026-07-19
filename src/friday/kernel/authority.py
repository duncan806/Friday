"""Non-negotiable judgment authority (implementation-spec §8, decisions D2/D5).

This is the code location of the differentiator surfaced in the design review
(§6.1): GPT is a tireless executor with immense capability, but it can never
decide *whether* to stop, redesign, or deliver a verdict. Those directive kinds
require a human in the directive's origin. Enforced here in code — not a prompt
suggestion an agent can ignore.
"""

from ..domain import Directive, AUTHORITY_KINDS
from ..errors import AuthorityBreach


class Authority:
    def can_issue(self, directive: Directive, actor: str) -> bool:
        if directive.kind in AUTHORITY_KINDS:
            return "human" in (directive.origin or "")
        return True

    def gate(self, directive: Directive, actor: str) -> Directive:
        """Approve a directive or raise AuthorityBreach. Only gate() sets
        approved=True, and the router refuses any directive not so marked."""
        if not self.can_issue(directive, actor):
            raise AuthorityBreach(
                f"actor {actor!r} may not issue a {directive.kind!r} directive "
                f"(origin={directive.origin!r}); halt/redesign/verdict require "
                f"human authority")
        directive.approved = True
        return directive
