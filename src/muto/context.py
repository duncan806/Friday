"""Deterministic prompt context budgeting. Canonical reports are never changed."""

import json
from pathlib import Path

import yaml


class ContextManager:
    def __init__(self, root: Path, budget_chars: int = 60000, recent_reports: int = 6):
        self.root = Path(root)
        self.budget = max(4000, int(budget_chars))
        self.recent = max(1, int(recent_reports))
        self.path = self.root / "context.json"

    def _summary(self, path: Path) -> str:
        """Extract only the report schema; no model judgment or invented prose."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            report = data.get("report", {}) if isinstance(data, dict) else {}
            action = " ".join(str(report.get("action_taken", "")).split())[:240]
            stuck = " ".join(str(report.get("where_stuck", "")).split())[:400]
            return f"{path.stem}: action={action!r}; stuck={stuck!r}"
        except (OSError, yaml.YAMLError):
            return f"{path.stem}: unreadable report"

    def build(self, paths: list[Path]) -> tuple[str, dict]:
        paths = sorted(paths)
        full = [(p, p.read_text(encoding="utf-8")) for p in paths]
        raw_chars = sum(len(text) for _, text in full)
        selected = list(full)
        compacted = []
        while sum(len(text) for _, text in selected) > self.budget and len(selected) > self.recent:
            compacted.append(selected.pop(0)[0])
        summaries = [self._summary(p) for p in compacted]
        chunks = []
        if summaries:
            chunks.append("# COMPACTED EARLIER REPORTS\n" + "\n".join(summaries))
        chunks.extend(text for _, text in selected)
        text = "\n\n".join(chunks)
        # A single pathological recent report is clipped, while its file remains intact.
        if len(text) > self.budget:
            text = text[-self.budget:]
        state = {
            "budget_chars": self.budget,
            "used_chars": len(text),
            "raw_chars": raw_chars,
            "usage_percent": round(100 * len(text) / self.budget, 1),
            "reports_total": len(paths),
            "reports_compacted": len(compacted),
            "recent_reports_full": len(selected),
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        return text, state


def read_context(root: Path) -> dict:
    try:
        return json.loads((Path(root) / "context.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
