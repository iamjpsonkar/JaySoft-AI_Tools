---
description: Show behavioral test coverage estimate. Supports generating tests for gaps.
---

Parse $ARGUMENTS for optional flags, then call jsat__get_behavioral_coverage:

IMPORTANT — jsat__get_behavioral_coverage takes ONLY an optional `service`
parameter. It does NOT accept a `path` parameter at all; passing one is a
fabricated argument the tool will ignore or reject. A positional path in
$ARGUMENTS cannot be sent to the tool directly — see the resolution rule below.

Supported flags:
  --generate       → after showing gaps, call jsat__generate_unit_test for top uncovered paths
  --service <name> → scope to one service (the ONLY native scoping this tool supports —
                      also avoids timeout on large codebases)
  --limit N        → show only top N uncovered paths (default: all for display; see
                      the --generate cap below, which is independent of display --limit)
  (no flag, no --service, positional path given) → see path-resolution rule below
  (no flag, no --service, no path)               → full, unscoped coverage report

"TOP" UNCOVERED PATHS — ranking criterion (used by both the displayed list and
--generate; do not rank by whatever order the tool happens to return): rank by, in
priority order: (1) public API endpoints from jsat__list_endpoints, (2) exported/
public functions with the highest cyclomatic complexity if available from
jsat__get_function, (3) functions on a breaking-severity blast-radius path if that
data is already at hand from an earlier step this session, (4) everything else in
the tool's original order. This mirrors why coverage matters — an uncovered public
endpoint is a materially bigger risk than an uncovered private helper — and gives a
reproducible answer to "top" instead of an implicit, undocumented one.

--generate DEFAULT CAP: if --generate is given WITHOUT --limit, do not generate a
test for every uncovered path found — on a large or low-coverage codebase this is
unbounded (could be hundreds of jsat__generate_unit_test calls). Default to the top
5 by the ranking above, print "Generating tests for top 5 of <N> uncovered paths —
pass --limit N to generate more," and let an explicit --limit override that default
in either direction (including generating fewer, e.g. --limit 2).

Path-resolution rule (the tool has no native path scoping): if a positional path is
given without --service:
  1. Call jsat__list_services() and check whether the path maps cleanly onto one
     service (e.g. the path is that service's directory). If so, call
     jsat__get_behavioral_coverage(service=<that name>) — native scoping, preferred.
  2. Otherwise, call jsat__get_behavioral_coverage() unscoped, then filter the
     returned uncovered-functions/endpoints list to entries whose file path starts
     with the given path — client-side filtering, not a tool capability. State this
     explicitly in the report so the user doesn't assume the scan itself was
     narrower/faster than a full pass.
  3. LARGE-REPO FALLBACK: an unscoped call is exactly the case most likely to be
     slow/timeout on a big repo, which is why step 1 tries native --service scoping
     first — but if no service match is found (step 1 fails) AND jsat__list_services()
     shows several services, do not fall straight to one unscoped call and hope; run
     jsat__get_behavioral_coverage(service=<name>) once per service instead (same
     "process one service at a time" pattern as /jsat-cohesion's LARGE-SCOPE
     STRATEGY), then merge and filter to the given path across the combined results.
     Only use a single unscoped call when there's just one service or the repo is
     small enough that scoping wouldn't help.

Examples:
  /jsat-coverage --service PaymentService
    → jsat__get_behavioral_coverage(service="PaymentService")  (native scoping)

  /jsat-coverage src/payment/
    → jsat__list_services() first to look for a matching service; if none, call
      jsat__get_behavioral_coverage() unscoped and filter results to src/payment/

  /jsat-coverage --generate --limit 5 --service PaymentService
    → coverage report + generate tests for 5 most critical uncovered paths

Show: overall % covered, uncovered functions, over-mocked tests, endpoint gaps.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
