"""Event bus (implementation-spec §4).

Every state change is materialized to events.jsonl (append-only). Surfaces tail
it incrementally; recovery replays it. status.json remains a derived snapshot.
"""

from .events import Event, EVENT_KINDS
from .log import EventLog

__all__ = ["Event", "EVENT_KINDS", "EventLog"]
