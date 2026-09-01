---
description: Validate one service's readiness — CLAUDE.md completeness, catalog registration, auth coverage, test gaps, and index freshness for that service.
---

Parse $ARGUMENTS for the target service name (required — this is scoped, not repo-wide).

Usage:
  /jsat-service-health-check <ServiceName>

Examples:
  /jsat-service-health-check PaymentService
  /jsat-service-health-check jsat

Difference from `/jsat doctor`: doctor checks JSAT's own health (index, AI provider,
MCP connection). This checks the health of ONE SERVICE inside the indexed codebase —
whether it's actually ready to be worked on / shipped / handed off.

## Phase 1 — Does it exist in the graph?

Call: jsat__list_services() — confirm <ServiceName> is present. If not found,
suggest the closest match by name and stop (don't guess a health report for a
service that isn't indexed).

Call: jsat__list_endpoints(service=<ServiceName>) — endpoint count, auth coverage.
Call: jsat__get_auth_coverage() filtered to this service's endpoints, if available.

Print: "🔍 Phase 1/4 — Found: <N> files, <N> endpoints, <N> unauthenticated"

## Phase 2 — Documentation completeness

Check for a CLAUDE.md (or equivalent) at the service's entry-point directory via
jsat__query(question="does <ServiceName> have documented setup, dependencies, and
architecture notes?", service=<ServiceName>). Flag missing: purpose, how to run
locally, key dependencies, ownership.

FALLBACK if jsat__query's response IS or STARTS WITH "[AI unavailable" (the
actual string includes a reason after a colon, e.g. "[AI unavailable: ..." —
match on prefix, not exact equality, or this check silently never triggers).
A down/unconfigured AI provider takes the whole tool with it — common, not
rare. When it fires: skip the semantic
question and check directly via Bash/Read instead — locate the service's root
directory (from Phase 1's file list) and look for CLAUDE.md / README.md there;
if found, grep it for the four required topics (purpose, local run instructions,
dependencies, ownership/owner) as plain keyword presence rather than a judged
answer. This is a weaker check than the AI-graded version (keyword presence
isn't the same as "actually documented well"), so mark the result "keyword-checked,
not AI-graded" in the report so the verdict isn't overstated.

Print: "📄 Phase 2/4 — Docs: <complete/partial/missing> — <what's missing> (<query|keyword-fallback>)"

## Phase 3 — Quality signals

Call: jsat__get_test_gaps(path=<service path>) — top 3 uncovered paths.
Call: jsat__security_review(path=<service path>) — critical/high findings only.
Call: jsat__blast_radius(target=<service entry point>, severity_filter=["breaking"])
  — anything currently in a breaking state relative to its dependents.

Print: "🧪 Phase 3/4 — Quality: <N> test gaps, <N> security findings, <N> breaking"

## Phase 4 — Verdict

Score the service: READY / NEEDS WORK / NOT READY based on:
  - READY: docs complete, no critical/high security findings, no breaking impacts
  - NEEDS WORK: minor gaps (missing docs OR test gaps, not both) AND no critical/high
    security findings — medium/low security findings alone land here, not in NOT READY
  - NOT READY: any critical OR high security finding, any breaking impact, or missing
    core docs combined with test gaps (both gaps at once, not just one)

Print final summary:
  🏥 Service: <name>
  📊 Verdict: READY / NEEDS WORK / NOT READY
  📄 Docs: <status>
  🧪 Test gaps: <N>
  🔒 Security: <N critical/high>
  💥 Breaking: <N>
  Top recommendation: <one specific first action>


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct
verdict and reasoning — interpret results in plain language. Do not echo raw JSON.
