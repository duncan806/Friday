"""Event types materialized to events.jsonl (implementation-spec §4.1)."""

from dataclasses import dataclass, field
import json

EVENT_KINDS = (
    "boot", "check", "task_planted",
    "round_started", "round_done", "build_failed", "integrity_breach",
    "question_asked", "answer_given",          # A안 round-trip channel
    "human_turn", "claude_turn",               # conversation
    "directive_issued", "directive_applied",
    "cycle_status", "notify",
)


@dataclass
class Event:
    kind: str
    ts: str = ""
    payload: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {"kind": self.kind, "ts": self.ts, "payload": self.payload},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, line: str) -> "Event":
        data = json.loads(line)
        return cls(data.get("kind", ""), data.get("ts", ""), data.get("payload", {}) or {})
