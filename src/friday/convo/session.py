"""Conversation session — human⇄Claude turns, persisted as JSONL (spec §5.1)."""

import json
from pathlib import Path

from ..domain import Turn, ConversationState


class Session:
    def __init__(self, root: Path, session_id: str):
        self.root = Path(root)
        self.session_id = session_id
        self.dir = self.root / "convo"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"session_{session_id}.jsonl"

    def append_turn(self, turn: Turn) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn.__dict__, ensure_ascii=False) + "\n")

    def load(self) -> ConversationState:
        turns: list = []
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                turns.append(Turn(**{k: d[k] for k in Turn.__dataclass_fields__ if k in d}))
        return ConversationState(session_id=self.session_id, turns=turns)

    def count(self) -> int:
        state = self.load()
        return len(state.turns)
