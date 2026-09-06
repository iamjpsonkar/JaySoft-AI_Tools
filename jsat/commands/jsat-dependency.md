---
description: Audit a dependency before adding or bumping it — known CVEs, who imports it, how critical those paths are, and what the upgrade touches.
---

Parse $ARGUMENTS for the dependency (or the command runs on the whole manifest).

Supported flags:
  --scope         → audit every dependency in the manifest (default is one dependency at a time)
  --cvss <min>    → only report CVEs at or above this score (default 7.0)
  --dry-run       → report only; do not modify the manifest

Examples:
  /jsat-dependency requests --cvss 5
    → everything about the requests dependency: imports, CVEs ≥5, upgrade impact
  /jsat-dependency --scope
    → the whole dependency manifest, highest-severity first

THIS IS NOT A NEW MCP CAPABILITY: it combines the CVE lookup (jsat__get_dependency_cves),
import graph (jsat__get_consumers), and upgrade impact into one decision.

## Phase 1 — Locate the dependency in the manifest

Find every manifest that declares it (requirements.txt / pyproject.toml / package.json /
Cargo.toml — whatever the repo uses), the declared version range, and what pins it.
If the name was not exact, do not guess — say which names are close. \
Print: "🗂️ Phase 1/4 — <manifest>: <declared range>"

## Phase 2 — Who imports it and how critical is that

Call: jsat__get_consumers(target=<dependency name>) and jsat__query(question="which
files import or require <dependency>?") to enumerate import sites. For each site, run
jsat__blast_radius(target=<the importing file>) and label the import path by the
criticality of what it feeds: a request endpoint that takes user input is critical; a
one-off script is not. Half the risk of any dependency is on this side — the same CVE
is a crisis in one deployment position and a non-event in another.
Print: "🧭 Phase 2/4 — <N> import sites, <M> critical (feed user-facing endpoints)"

## Phase 3 — Known CVEs

Call: jsat__get_dependency_cves(path=<repo>, cvss_min=<min global default 7>) and filter
for this dependency, OR scan the whole manifest if --scope. For each CVE report:
  - GHSA / advisory id and CVSS
  - whether the affected version range overlaps what the repo pins
  - whether the importing code actually reaches the vulnerable code path (the
    import site's use of the library's affected function — flag when it does not, and
    mark the CVE "not reachable" rather than pretending it does not exist)
Print: "🔴 Phase 3/4 — <N> CVEs at/above CVSS <min>; <K> reachable, <J> not reachable"

## Phase 4 — The decision

If --dry-run: produce the recommendation and stop.
Otherwise apply the smallest safe change:
  - vulnerable + reachable → bump to a patched version if one exists (verify: does
    the new version's API still exist for the import sites — jsat__get_consumers again,
    since the same import graph that found the site catches a breaking bump), else drop
    + replace with the closest maintained alternative
  - vulnerable + not reachable → pin the next patched version at the next opportunity;
    add a knowledge note so the follow-up happens. Do NOT force an upgrade that breaks
    a critical import path in the same commit.
  - not vulnerable → report "current version, no CVEs at threshold" and stop.

Print final summary:
  🔒 <dependency>: <patched|replaced|clean> — <N> CVEs (<K> reachable), <M> import sites affected
  Recommended follow-up: <anything deferred>

Do NOT run a blind `install --upgrade` across the manifest, do NOT bump major versions
as a "security fix" without the import-site check, and never edit a lockfile without
stating what the new resolvable set is.

## Learning from the run

Call jsat__knowledge_add(
  text="DEPENDENCY <name>: <declared range> → <result>, <N> reachable CVEs, <M> import sites",
  category="dependency")
so the next audit of the same package starts from the previous outcome.

BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Always do Phase 2 before Phase 3 — the import map is what turns a
CVE list into a decision. When jsat__get_dependency_cves needs the network / an API
key and it is unavailable, report that explicitly as "CVE lookup unavailable" and still
deliver the import map and upgrade-impact analysis; never fabricate a CVE number.
Never change the manifest in --dry-run mode.