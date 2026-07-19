"""Conversation engine (implementation-spec §5.2).

human_says() records the human turn, builds budgeted context (conversation +
read-only execution state), calls the Claude *advisor*, records the reply,
extracts a Directive, and — only after the kernel's Authority gate — submits it
to the Router. The engine never touches the execution engine directly (D4).

Dependency-injected: claude_fn(prompt)->str and clock()->ts keep it testable
without a real CLI (mirrors how Orchestrator injects agents).
"""

from pathlib import Path

from ..bus import Event, EventLog
from ..domain import Turn, Directive
from .session import Session
from .memory import ConversationMemory
from .directive import extract_directive

ADVISOR_PROMPT = """You are Claude, the slow, insightful partner in Friday — the human's advisor \
on direction and judgment (the "why" and "is this right"), while GPT does the fast execution.

Converse naturally with the human. When — and only when — the exchange reaches a \
concrete decision that execution should act on, append one fenced block:

```directive
kind: steer | halt | resume | redesign | verdict | noop
text: <the direction, in one or two sentences>
```

Use `halt`, `redesign`, or `verdict` only when the human clearly decides so \
(these carry the human's authority). Otherwise omit the block or use noop.

# CONTEXT
{{context}}

# HUMAN
{{human}}
"""


class ConversationEngine:
    def __init__(self, root, authority, router, claude_fn, *, session_id="001",
                 budget_chars=40000, recent_turns=12, clock=lambda: "",
                 log=None, exec_summary_fn=lambda: ""):
        self.root = Path(root)
        self.authority = authority
        self.router = router
        self.claude_fn = claude_fn
        self.session = Session(root, session_id)
        self.memory = ConversationMemory(budget_chars, recent_turns)
        self.clock = clock
        self.log = log or EventLog(root)
        self.exec_summary_fn = exec_summary_fn

    def _next_directive_id(self) -> str:
        d = self.root / "directives"
        n = len(list(d.glob("dir_*.json"))) if d.exists() else 0
        return f"{n + 1:03d}"

    def _prompt(self, context: str, human: str) -> str:
        return (ADVISOR_PROMPT
                .replace("{{context}}", context)
                .replace("{{human}}", human))

    def human_says(self, text: str) -> Directive | None:
        """One conversational exchange. Returns the Directive it produced (if any)."""
        ts = self.clock()
        self.session.append_turn(Turn("human", text, ts))
        self.log.append(Event("human_turn", ts, {"text": text}))

        context = self.memory.build(self.session.load(), self.exec_summary_fn())
        reply = self.claude_fn(self._prompt(context, text))

        did = self._next_directive_id()
        directive = extract_directive(reply, did)
        ts2 = self.clock()
        self.session.append_turn(
            Turn("claude", reply, ts2, directive_id=(directive.id if directive else None)))
        self.log.append(Event("claude_turn", ts2, {"text": reply}))

        if directive is None:
            return None
        # Human-origin directive: the kernel gate permits even halt/verdict.
        directive = self.authority.gate(directive, actor="human")
        self.router.submit(directive)
        self.log.append(Event("directive_issued", ts2,
                              {"id": directive.id, "kind": directive.kind}))
        return directive
