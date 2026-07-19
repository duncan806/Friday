"""Conversation memory — budgeted context for the human⇄Claude dialogue.

Recent turns verbatim; older turns summarized; the current execution state
folded in so the advisor (Claude) can reason about what GPT is doing. Clipping
happens at a turn boundary, never mid-turn (design review Med#5 principle).
"""

from ..domain import ConversationState


class ConversationMemory:
    def __init__(self, budget_chars: int = 40000, recent_turns: int = 12):
        self.budget = max(2000, int(budget_chars))
        self.recent = max(1, int(recent_turns))

    def build(self, state: ConversationState, exec_summary: str = "") -> str:
        turns = state.turns
        recent = turns[-self.recent:]
        older = turns[:-self.recent] if len(turns) > self.recent else []

        parts: list[str] = []
        if older:
            summary = "; ".join(f"{t.role}: {t.text[:80]}" for t in older)
            parts.append("# EARLIER CONVERSATION (summary)\n" + summary)
        if exec_summary:
            parts.append("# EXECUTION STATE (read-only)\n" + exec_summary)
        parts.extend(f"[{t.role}] {t.text}" for t in recent)

        text = "\n\n".join(parts)
        # Preserve leading sections; drop whole leading turns if over budget.
        while len(text) > self.budget and len(recent) > 1:
            recent = recent[1:]
            body = [p for p in parts if not p.startswith("[")] + [f"[{t.role}] {t.text}" for t in recent]
            text = "\n\n".join(body)
        return text
