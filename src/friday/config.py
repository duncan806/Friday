"""Configuration schema, defaults, and validation (implementation-spec §10).

Defaults reproduce the original validate-mode behavior exactly: `mode: validate`
with every collaborate key at 0. An existing workspace or a fresh `friday init`
therefore behaves as before until collaborate features are explicitly opted in.
"""

from pathlib import Path

import yaml

from .errors import ConfigError

DEFAULTS = {
    "mode": "validate",
    "bandwidth_level": 1,
    "round_budget": 30,
    "call_budget": 0,
    "auth_mode": "subscription",
    "timeout_seconds": 600,
    "context_budget_chars": 60000,
    "context_recent_reports": 6,
    "intent_providers": ["codex", "claude"],
    "window": True,
    # collaborate-mode (all off by default → no behavior change)
    "dialogue_turns": 0,
    "claude_checkin_every": 0,
    "claude_on_build_fail": 0,
    "convo_budget_chars": 40000,
    "convo_recent_turns": 12,
}

_NONNEG_INT_KEYS = (
    "bandwidth_level", "round_budget", "call_budget", "timeout_seconds",
    "context_budget_chars", "context_recent_reports",
    "dialogue_turns", "claude_checkin_every", "claude_on_build_fail",
    "convo_budget_chars", "convo_recent_turns",
)


def validate(cfg: dict) -> dict:
    mode = cfg.get("mode", "validate")
    if mode not in ("validate", "collaborate"):
        raise ConfigError(f"unknown mode: {mode!r} (expected 'validate' or 'collaborate')")
    for key in _NONNEG_INT_KEYS:
        v = cfg.get(key, DEFAULTS[key])
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ConfigError(f"{key} must be a non-negative integer, got {v!r}")
    return cfg


def merged(cfg: dict | None) -> dict:
    """DEFAULTS overlaid with the given config, then validated."""
    out = dict(DEFAULTS)
    out.update(cfg or {})
    return validate(out)


def load(root: Path) -> dict:
    try:
        raw = yaml.safe_load((Path(root) / "config.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        raw = {}
    return merged(raw)
