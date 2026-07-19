"""When to call the slow, expensive insight — Claude (spec §7, §4.5).

The cost answer to "won't calls explode?": the fast executor (GPT) runs most
rounds cheaply; the expensive judge (Claude) is invoked only on a trigger or an
explicit human request. These rules are the sole automatic Claude entry point.
"""

from dataclasses import dataclass


@dataclass
class TriggerConfig:
    claude_checkin_every: int = 0     # call Claude every R rounds (0 = off)
    claude_on_build_fail: int = 0     # call Claude after N consecutive build failures (0 = off)
    dialogue_turns: int = 0           # A안 round-trip cap (0 = off)


def should_call_claude(rounds, cfg: TriggerConfig) -> str | None:
    """rounds: list of RoundResult (each with .build_failed). Return a human
    reason string if Claude should be consulted now, else None."""
    n = len(rounds)
    if n == 0:
        return None
    k = cfg.claude_on_build_fail
    if k > 0 and n >= k and all(getattr(r, "build_failed", False) for r in rounds[-k:]):
        return f"build failed {k}x consecutively"
    e = cfg.claude_checkin_every
    if e > 0 and n % e == 0:
        return f"scheduled check-in every {e} rounds"
    return None
