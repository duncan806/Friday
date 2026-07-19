"""Reverse bandwidth filter — strip How/code leaking Codex -> Claude.

Symmetric counterpart to bandwidth_filter (which strips intent/Why on the
Claude -> Codex path). When the round-trip channel is enabled (dialogue_turns>0,
spec §6.1 / design A안), a Codex question routed to Claude must not carry code,
paths, or diffs, or Claude's "cannot see code" boundary breaks.

Conservative by design (D3): remove code fences, diff lines, src/ references,
and file-path-like tokens; return the removed spans for audit. Identifier-level
leakage cannot be fully removed by regex and is left visible in the dropped log
(the same honest trade-off bandwidth_filter makes for intent — README U1).
"""

import re

_CODEFENCE = re.compile(r"```.*?```", re.DOTALL)
_DIFF = re.compile(r"^[+-].*$", re.MULTILINE)
_SRC = re.compile(r"\bsrc/[\w./-]+")
_PATH = re.compile(
    r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|c|cc|cpp|h|hpp|rs|go|java|rb|kt|swift|"
    r"md|json|ya?ml|toml|cfg|ini|sh|bat|html|css)\b",
    re.IGNORECASE,
)


def reverse_filter(text: str) -> tuple[str, list[str]]:
    """Return (kept text, list of dropped code/path spans)."""
    if not text:
        return "", []
    dropped: list[str] = []

    def drop(match: "re.Match") -> str:
        span = match.group(0).strip()
        if span:
            dropped.append(span)
        return " "

    t = _CODEFENCE.sub(drop, text)
    t = _DIFF.sub(drop, t)
    t = _SRC.sub(drop, t)
    t = _PATH.sub(drop, t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip(), dropped
