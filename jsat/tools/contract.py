"""jsat.tools.contract — Tool 5: API Contract Validator."""
from __future__ import annotations

import math
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsat.tools import BaseTool

_SPEC_GLOBS = ("openapi*.yaml", "openapi*.json", "swagger*.yaml", "asyncapi*.yaml")


@dataclass
class ContractReport:
    changes: list[dict[str, Any]]
    breaking_count: int
    compat_score: int
    migration_guide: str
    duration_ms: int


class ContractTool(BaseTool):
    """Diffs OpenAPI/AsyncAPI specs between git branches."""

    def run(self, base: str = "main", head: str = "HEAD",
            format: str = "auto") -> ContractReport:
        import structlog
        log = structlog.get_logger(__name__)
        log.info("contract_start", base=base, head=head, format=format)
        t0 = time.monotonic()

        root = self._repo_root()
        specs = self._find_specs(root)
        log.info("contract_specs_found", count=len(specs))

        all_changes: list[dict] = []
        for spec in specs:
            diff = self._git_diff(spec, base, head)
            if diff:
                changes = self._classify(diff)
                log.debug("contract_spec_classified", spec=str(spec.name),
                          total=len(changes),
                          breaking=sum(1 for c in changes if c["is_breaking"]))
                for c in changes:
                    c["spec"] = str(spec.relative_to(root))
                all_changes.extend(changes)

        breaking = sum(1 for c in all_changes if c["is_breaking"])
        score = max(0, round(100 * math.exp(-0.15 * breaking)))
        guide = self._guide(all_changes, base, head)
        duration_ms = round((time.monotonic() - t0) * 1000)

        log.info("contract_done", breaking=breaking, score=score, duration_ms=duration_ms)
        return ContractReport(changes=all_changes, breaking_count=breaking,
                              compat_score=score, migration_guide=guide,
                              duration_ms=duration_ms)

    def _repo_root(self) -> Path:
        try:
            r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return Path(r.stdout.strip())
        except Exception:
            pass
        return Path.cwd()

    def _find_specs(self, root: Path) -> list[Path]:
        found = []
        for pat in _SPEC_GLOBS:
            found.extend(root.rglob(pat))
        return list(dict.fromkeys(found))  # dedup

    def _git_diff(self, spec: Path, base: str, head: str) -> str:
        try:
            r = subprocess.run(
                ["git", "diff", f"{base}...{head}", "--", str(spec)],
                capture_output=True, text=True, timeout=15,
            )
            return r.stdout
        except Exception:
            return ""

    def _classify(self, diff: str) -> list[dict]:
        changes: list[dict] = []
        removed: list[str] = []
        added: list[str] = []

        for line in diff.splitlines():
            if line.startswith("---") or line.startswith("+++"):
                continue
            if line.startswith("-"):
                removed.append(line[1:].strip())
            elif line.startswith("+"):
                added.append(line[1:].strip())

        added_set = set(added)

        for content in removed:
            norm = content.lower()
            # Endpoint method lines (e.g. "get:", "post:", "/path/to/resource:")
            is_endpoint = bool(re.match(r'(get|post|put|patch|delete|head|options)\s*:', norm))
            is_path = bool(re.match(r'/\S', norm))
            # Field removals in schemas
            is_field_removal = any(kw in norm for kw in ("required", "type:", "schema:", "$ref:"))
            # Endpoint removed outright (not just renamed)
            if (is_endpoint or is_path) and content not in added_set:
                changes.append({"content": content, "is_breaking": True,
                                "change_type": "endpoint_removed",
                                "reason": "Endpoint or path removed with no replacement"})
            elif is_field_removal and content not in added_set:
                changes.append({"content": content, "is_breaking": True,
                                "change_type": "field_removed",
                                "reason": "Required field or type constraint removed"})
            else:
                changes.append({"content": content, "is_breaking": False,
                                "change_type": "removed"})

        for content in added:
            changes.append({"content": content, "is_breaking": False, "change_type": "added"})

        return changes

    def _guide(self, changes: list[dict], base: str, head: str) -> str:
        breaking = [c for c in changes if c["is_breaking"]]
        if not breaking:
            return ""
        lines = [f"# Migration Guide — `{base}` → `{head}`", ""]
        for i, c in enumerate(breaking, 1):
            reason = c.get("reason", "Breaking change")
            lines.append(f"{i}. **{reason}** in `{c.get('spec','?')}`: `{c['content']}`")
        return "\n".join(lines)
