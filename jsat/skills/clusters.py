"""jsat.skills.clusters — Named skill sequences (workflow shortcuts)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jsat.skills.registry import SkillsRegistry

BUILT_IN_CLUSTERS: dict[str, list[str]] = {
    "start-session":          ["quickstart", "status", "loadrules"],
    "new-feature":            ["newfeature", "blast-radius", "contract-check", "commit-and-pr"],
    "pre-merge":              ["multi-review", "qa", "service-health-check", "security-review"],
    "incident":               ["incident-investigation", "blast-radius", "diff"],
    "security-release":       ["vuln-triage", "vuln-fix", "security-review"],
    "db-schema-change":       ["migration-plan", "blast-radius", "contract-check"],
    "knowledge-maintenance":  ["syncknowledge", "saveknowledge", "update-feature"],
}


def list_clusters() -> list[str]:
    """Return names of all built-in clusters."""
    return list(BUILT_IN_CLUSTERS)


def run_cluster(name: str, registry: SkillsRegistry) -> list[str]:
    """Run all skills in a named cluster sequentially. Returns list of outputs."""
    from jsat._exceptions import SkillNotFound

    skills = BUILT_IN_CLUSTERS.get(name)
    if skills is None:
        raise ValueError(
            f"Unknown cluster '{name}'. Available: {list(BUILT_IN_CLUSTERS)}"
        )

    results: list[str] = []
    for skill in skills:
        try:
            output = registry.run(skill)
            results.append(f"[{skill}] {output}")
        except SkillNotFound:
            results.append(f"[{skill}] not installed — skipping")
        except Exception as e:
            results.append(f"[{skill}] error: {e}")
    return results
