"""Mode policy — validate vs collaborate (implementation-spec §8, decision D1).

validate     : the original Friday. Information asymmetry — Claude and Codex
               cannot see each other's half. Forward filter on, all integrity
               asserts on. Purpose: validation.
collaborate  : the Iron Man / FRIDAY model. Role asymmetry — they may see each
               other; the split is slow-insight (Claude) vs fast-execution
               (GPT). No information-hiding asserts, forward filter off,
               dialogue allowed. Authority (kernel) still enforced.
"""

from ..errors import ConfigError


class Mode:
    VALIDATE = "validate"
    COLLABORATE = "collaborate"
    NAMES = (VALIDATE, COLLABORATE)

    def __init__(self, name: str = VALIDATE):
        if name not in self.NAMES:
            raise ConfigError(f"unknown mode: {name!r} (expected one of {self.NAMES})")
        self.name = name

    @property
    def collaborate(self) -> bool:
        return self.name == self.COLLABORATE

    def policy(self) -> dict:
        """Return the enforcement policy for this mode."""
        if self.name == self.VALIDATE:
            return {
                "information_asymmetry": True,
                "dialogue_allowed": False,
                "forward_filter": True,
                "claude_profile": "isolated_exec",
                "asserts": ("claude_isolation", "surface_cwd", "codex_prompt_clean"),
            }
        return {
            "information_asymmetry": False,
            "dialogue_allowed": True,
            "forward_filter": False,
            "claude_profile": "advisor",
            "asserts": (),
        }
