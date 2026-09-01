---
description: Assess the blast radius of bumping a dependency — which files import it, how critical those paths are, and whether the current version has known CVEs.
---

Parse $ARGUMENTS for optional flags, then positional arg: <package> (the dependency
name as it appears in the manifest, e.g. "requests", "lodash").

Supported flags:
  --service <name>   → scope the import search to one service
  --to <version>     → the target version being considered (used only for the summary
                        label; this command does not check the target version's own
                        changelog/breaking-changes — that's a manual read of its release notes)

Examples:
  /jsat-upgrade-impact requests
  /jsat-upgrade-impact --to 3.0.0 --service PaymentService pydantic

This command answers "what breaks if I bump this?" — it does not perform the upgrade
itself. It combines existing analytical tools; no new MCP capability is required.

## Phase 1 — Find every importer

Call: jsat__query(question="which files import or depend on <package>?", service=<name if given>).
This is the scope of everything that could be affected by a version bump.

FALLBACK if jsat__query returns "[AI unavailable]" (a down/unconfigured AI provider
takes the whole tool with it — this happens): use Bash
(`grep -rl "^import <package>\|^from <package>" <path>`) as a direct substitute.
This is exact-match text search, not semantic, so it can miss re-exported or
dynamically-imported usages that a graph-native query might catch — mark the
result as "Bash-enumerated" in the report so the user knows the coverage caveat.

Print: "🔍 Phase 1/4 — Importers: <N> files depend on <package> (<query|bash-fallback>)"

## Phase 2 — Current risk (is staying on the old version dangerous?)

Do NOT call jsat__get_dependency_cves directly — as of this writing it
unconditionally returns `status: "not_implemented"` regardless of the repo, so it
will never produce real data. Instead call jsat__security_review(path=".") and
read its `cves` field — that is the actual working CVE data path.

Print: "🔒 Phase 2/4 — Current version CVEs: <N> (<severity breakdown>, via security_review)"

## Phase 3 — Blast radius of the importers

LARGE DEPENDENCY STRATEGY: if Phase 1 found more than ~20 importing files, group by
service/directory and call blast_radius once per group rather than once per file —
same pattern as /jsat-merge's large-merge strategy.

CAVEAT: blast_radius's severity labels run hot — a plain one-hop function call is
routinely labeled "breaking" even when it's unremarkable. Treat the severity counts
below as a rough signal of surface area, not a literal breaking-change count.

For each importing file (or group): call jsat__blast_radius(target=<file>) to see
how deep the impact would ripple if that file's behavior changed due to the bump.
Aggregate: how many importers sit on a path with `breaking`-severity downstream impact.

Print: "💥 Phase 3/4 — Impact: <N> importers on breaking-impact paths, <N> isolated/low-risk"

## Phase 4 — Recommend

Synthesize Phases 1-3 into a recommendation:
  - LOW RISK: few importers, none on breaking paths → safe to bump directly
  - MEDIUM RISK: several importers on breaking paths → bump behind a feature branch,
    run /jsat-test-gaps on the importing files first, review before merging
  - HIGH RISK: many importers on breaking paths AND current version has CVEs →
    upgrading is urgent despite the risk; do it with the full /jsat-test-gaps +
    /jsat-review cycle rather than deferring

IMPORTANT — a LOW RISK verdict is only as trustworthy as Phase 1's importer
list. If Phase 1 fell back to Bash grep (AI unavailable), that list is
exact-match text search and — as already noted in Phase 1 — misses
re-exported and dynamically-imported usages. "Few importers found" from a
Bash-fallback scan is not the same claim as "few importers found" from the
graph: the former can just mean the search missed some, not that few exist.
The LARGE DEPENDENCY STRATEGY chunking in Phase 3 (group by service/directory
once >20 importers) still applies mechanically either way, but it does not
compensate for this — grouping a short, possibly-incomplete list still
produces a short, possibly-incomplete grouped list. Do NOT issue a bare LOW
RISK verdict off a Bash-fallback importer count. Instead:
  - Cap it at "LOW RISK (provisional — importer list is Bash-enumerated, not
    graph-verified; re-run once the AI backend is back before treating this
    as safe to bump directly)".
  - MEDIUM/HIGH verdicts are not weakened by the same gap (an incomplete
    importer list can only under-count risk, never manufacture false
    breaking paths), so no caveat is needed there beyond the Phase 1 label.

Print final summary:
  📦 Package: <package> <current version if known> → <target version if given>
  📁 Importers: <N> files (<N> on breaking-impact paths) [Bash-enumerated, provisional — if applicable]
  🔒 Current CVEs: <N>
  🎯 Verdict: LOW / MEDIUM / HIGH RISK
  First step: <specific file to check/test first>

This command does not read the target version's own release notes or changelog —
if the target version is known to have breaking API changes, that must be checked
separately (e.g. via /jsat-changelog if the package itself is another indexed
service, or by reading its published changelog directly).


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct
risk verdict and reasoning — interpret results in plain language. Do not echo raw
JSON. Never state a risk level without citing the specific counts it's based on.
