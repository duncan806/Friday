"""Extract a Directive from Claude's advisory reply (implementation-spec §5).

Convention: the advisor may append a fenced ```directive block with `kind` and
`text`. Absence (or kind: noop) means "just conversation, do not steer
execution". Parsing is deterministic — no model judgment in this layer.
"""

import re

import yaml

from ..domain import Directive, DIRECTIVE_KINDS

_BLOCK = re.compile(r"```directive\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_directive(text: str, directive_id: str,
                      origin: str = "human+claude") -> Directive | None:
    match = _BLOCK.search(text or "")
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    kind = str(data.get("kind", "noop")).strip().lower()
    if kind not in DIRECTIVE_KINDS or kind == "noop":
        return None
    return Directive(id=directive_id, kind=kind,
                     text=str(data.get("text", "")).strip(), origin=origin)
