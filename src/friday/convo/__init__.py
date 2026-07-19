"""Conversation engine — the human talks with Claude (implementation-spec §5).

The human converses with the slow, insightful partner (Claude); that dialogue
produces Directives, and Directives reach the fast executor (GPT) only after
passing the kernel. The conversation never touches execution directly.
"""

from .engine import ConversationEngine, ADVISOR_PROMPT
from .session import Session
from .memory import ConversationMemory
from .directive import extract_directive

__all__ = [
    "ConversationEngine", "ADVISOR_PROMPT", "Session",
    "ConversationMemory", "extract_directive",
]
