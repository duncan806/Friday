"""Directive queue — kernel-approved directions flow to execution as files.

Every mutation is materialized (directives/dir_XXX.json), matching Friday's
file-is-source-of-truth principle (spec §7, §13). The router refuses any
directive that did not pass kernel.authority.gate (approved=True).
"""

import json
from pathlib import Path

from ..domain import Directive
from ..errors import AuthorityBreach


class Router:
    def __init__(self, root: Path):
        self.dir = Path(root) / "directives"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _write(self, path: Path, data: dict) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def submit(self, directive: Directive) -> Path:
        if not directive.approved:
            raise AuthorityBreach(
                f"directive {directive.id!r} reached the router without kernel approval")
        path = self.dir / f"dir_{directive.id}.json"
        self._write(path, dict(directive.__dict__))
        return path

    def pending(self, round_no: int) -> Directive | None:
        """The earliest submitted, not-yet-applied directive."""
        for path in sorted(self.dir.glob("dir_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("applied_round") is None:
                fields = Directive.__dataclass_fields__
                return Directive(**{k: data[k] for k in fields if k in data})
        return None

    def mark_applied(self, directive: Directive, round_no: int) -> None:
        path = self.dir / f"dir_{directive.id}.json"
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        data["applied_round"] = round_no
        self._write(path, data)
