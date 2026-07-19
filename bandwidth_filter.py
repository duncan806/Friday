"""muto bandwidth filter v0—regex based. (spec §5)

Channel schema:
  action_taken  always allowed
  where_stuck   always allowed
  expected      allowed only at LEVEL 2
  intent        always blocked

Even inside allowed fields, sentences judged to describe purpose/intent are
dropped. The caller preserves dropped sentences verbatim in reports/dropped/.

Known limitation (public, U1): intent leakage cannot be fully prevented.
This is not hidden; it is offset by the auditability of the dropped log.
"""

import re

ALLOWED_ALWAYS = ("action_taken", "where_stuck")
ALLOWED_LEVEL2 = ("expected",)
PASSTHROUGH = ("deviation", "round")  # metadata, not channel content

# Purpose/intent phrasing patterns (Korean + English)
INTENT_PATTERNS = [
    r"위해", r"위한", r"하려고", r"하고\s*싶", r"싶어서", r"원해서", r"목적", r"의도",
    r"필요해서", r"쓰려고", r"려는\s*것", r"하기\s*위함",
    r"\bin order to\b", r"\bso that\b", r"\bbecause I want\b",
    r"\bmy goal\b", r"\bintend(?:s|ed|ing)?\b", r"\bpurpose\b", r"\btrying to\b",
]
_INTENT_RE = re.compile("|".join(INTENT_PATTERNS), re.IGNORECASE)

_SENT_SPLIT = re.compile(r"(?<=[.!?다요음됨])\s+|\n+")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def apply_filter(report: dict, level: int) -> tuple[dict, list[str]]:
    """Return (passed report dict, list of dropped sentences)."""
    allowed = set(ALLOWED_ALWAYS)
    if level >= 2:
        allowed |= set(ALLOWED_LEVEL2)

    kept: dict = {}
    dropped: list[str] = []

    for key, value in report.items():
        if key in PASSTHROUGH:
            kept[key] = value
            continue
        text = str(value) if value is not None else ""
        if key not in allowed:
            # Block the intent field and any disallowed field wholesale
            # (including expected at LEVEL 1)
            if text.strip():
                dropped.append(f"[{key}] {text.strip()}")
            continue
        keep_sents, drop_sents = [], []
        for sent in _split_sentences(text):
            (drop_sents if _INTENT_RE.search(sent) else keep_sents).append(sent)
        kept[key] = " ".join(keep_sents)
        dropped.extend(f"[{key}] {s}" for s in drop_sents)

    return kept, dropped
