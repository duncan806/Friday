"""Append-only event log — primary source of truth for recovery/observability.

Single-writer append with flush (spec §4.2, §14). Surfaces poll tail() with a
line cursor; recovery uses replay(). Kept dependency-free and cross-platform;
heavier advisory locking is deferred (spec §13).
"""

from pathlib import Path
from typing import Iterator

from .events import Event


class EventLog:
    def __init__(self, root: Path):
        self.path = Path(root) / "events.jsonl"

    def append(self, ev: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(ev.to_json() + "\n")
            f.flush()

    def replay(self) -> Iterator[Event]:
        if not self.path.is_file():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield Event.from_json(line)
                except ValueError:
                    continue

    def tail(self, since_line: int = 0) -> tuple[list[Event], int]:
        """Return (events at or after `since_line`, next line cursor). Cheap
        incremental poll for surfaces."""
        events: list[Event] = []
        cursor = since_line
        if not self.path.is_file():
            return events, cursor
        with open(self.path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                cursor = i + 1
                if i < since_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(Event.from_json(line))
                except ValueError:
                    continue
        return events, cursor
