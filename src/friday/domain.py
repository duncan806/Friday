"""Shared domain types for Friday (implementation-spec §3).

These are the values that cross subsystem boundaries: a Directive (a decision
that flows human/Claude -> kernel -> execution) and conversation Turns. Kept
dependency-free so kernel, convo, route, and exec can all import them.
"""

from dataclasses import dataclass, field

# Directive kinds. AUTHORITY_KINDS may only be issued with a human in the
# origin (kernel.authority enforces this — spec §8, D2/D5): GPT can never
# decide to stop, redesign, or deliver a verdict.
DIRECTIVE_KINDS = ("steer", "halt", "resume", "redesign", "verdict", "noop")
AUTHORITY_KINDS = ("halt", "redesign", "verdict")


@dataclass
class Directive:
    id: str
    kind: str                       # one of DIRECTIVE_KINDS
    text: str = ""                  # direction injected into the execution engine
    origin: str = "human"           # "human" | "human+claude" | "trigger" | "exec"
    ts: str = ""                    # ISO8601, injected at the entry point (spec §12)
    applied_round: int | None = None
    approved: bool = False          # set True only by kernel.authority.gate


@dataclass
class Turn:
    role: str                       # "human" | "claude"
    text: str
    ts: str = ""
    directive_id: str | None = None


@dataclass
class ConversationState:
    session_id: str
    turns: list = field(default_factory=list)      # list[Turn]
    summary: str = ""                              # compacted older turns
    open_directives: list = field(default_factory=list)  # list[str] (Directive ids)
