"""jsat.skills.clusters — Named skill sequences (workflow shortcuts)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jsat.skills.registry import SkillsRegistry

# Ordered sequences of JSAT commands for common workflows.
#
# Every name here must be a real command shipped in jsat/commands/ — these
# previously referenced an older naming scheme (`quickstart`, `newfeature`,
# `multi-review`, `vuln-triage`, …) that never existed, so every cluster
# resolved to nothing and `run_cluster` only ever emitted "not installed".
BUILT_IN_CLUSTERS: dict[str, list[str]] = {
    "start-session":          ["index", "status", "knowledge"],
    "new-feature":            ["plan", "lazy", "blast-radius", "contract",
                               "pr-describe"],
    "pre-merge":              ["review", "test-gaps", "service-health-check",
                               "security"],
    "incident":               ["incident", "blast-radius", "recent"],
    "security-release":       ["security", "upgrade-impact", "verify"],
    "db-schema-change":       ["migration", "blast-radius", "contract"],
    "knowledge-maintenance":  ["knowledge", "decide", "runbook"],
}


def list_clusters() -> list[str]:
    """Return names of all built-in clusters."""
    return list(BUILT_IN_CLUSTERS)


def run_cluster(name: str, registry: SkillsRegistry) -> list[str]:
    """Run every skill in a named cluster in order. Returns one line per step.

    Note what this does and does not do. It dispatches through
    ``SkillsRegistry``, which executes only ``source.type == "script"``
    manifests; JSAT ships no such manifests, so on a stock install each step
    reports "not installed — skipping". The cluster is therefore useful today
    as the canonical *ordering* for a workflow — the same order the `/jsat`
    slash commands should be run in — rather than as an execution engine.
    """
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
