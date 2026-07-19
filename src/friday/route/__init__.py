"""Routing & triggers (implementation-spec §7).

Triggers decide *when* to spend the slow, expensive insight (Claude); the Router
carries kernel-approved Directives to the execution engine as files.
"""

from .triggers import TriggerConfig, should_call_claude
from .router import Router

__all__ = ["TriggerConfig", "should_call_claude", "Router"]
