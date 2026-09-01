---
description: Find functions and classes with no callers in the codebase — a graph inversion of blast-radius, not a new capability.
---

Parse $ARGUMENTS for optional flags, then positional arg: [path] (defaults to ".").

Supported flags:
  --service <name>   → scope to one service (avoids timeout on large codebases)
  --include-private  → also flag private/internal (_prefixed) functions (default: only
                        public API surface is flagged, since private dead code is lower
                        risk and often intentional scaffolding)

Examples:
  /jsat-dead-code
    → scan the whole indexed codebase for unreferenced functions/classes
  /jsat-dead-code --service PaymentService
    → scope to one service
  /jsat-dead-code src/legacy/
    → scope to one path

THIS IS NOT A NEW MCP CAPABILITY: blast_radius already computes inbound call edges
for any given symbol. This command just asks the inverse question — "which symbols
have ZERO inbound edges?" — across the whole codebase instead of one symbol at a time.

## Phase 1 — Candidate discovery

Call: jsat__query(question="list functions and classes in <path> that have no
callers anywhere in the indexed codebase") — this is the primary discovery step;
the graph already has full call-edge data, so this is a direct lookup, not inference.

If --service was given, scope the question to that service.

FALLBACK if jsat__query returns "[AI unavailable]" (query needs an LLM backend to
turn the graph data into an answer; a down/unconfigured AI provider takes the whole
tool with it, this is a known failure mode, not an edge case): enumerate candidate
symbols via Bash (`grep -n "^def \|^class "` per file under <path>, or the
language's equivalent), then for EACH candidate call jsat__blast_radius(target=<symbol>)
— blast_radius is pure graph traversal and does not need the AI backend. A symbol
with zero non-"safe" impacts and zero inbound CALLS edges in the result is a dead-code
candidate. This is slower (one call per candidate instead of one query) but stays
correct when jsat__query is down — mark results from this path as "Bash-enumerated"
in the report so the user knows it wasn't a single graph-native lookup.

Print: "🔍 Phase 1/3 — Candidates: <N> symbols with zero detected callers (<query|bash-fallback>)"

## Phase 2 — Exclude false positives

Dead-code detection over a static call graph produces false positives for anything
invoked indirectly. Before reporting a candidate as dead, exclude it if it matches
ANY of these patterns — do not flag them even if the graph shows zero direct callers:
  - Entry points: `main`, `if __name__ == "__main__"` blocks, CLI command functions
  - Framework-invoked handlers: route handlers, event listeners, signal handlers,
    pytest fixtures/tests (anything matching test_*, *_test, conftest.py content)
  - Public API surface explicitly re-exported via `__init__.py` / `__all__`
  - MCP tool registrations / decorated functions (`@tool`, `@app.route`, etc. —
    the decorator itself is a caller the static graph may not resolve)
  - Anything referenced only by string (dynamic dispatch, plugin registries,
    `getattr`-based calls) — call jsat__query(question="is <symbol> referenced by
    name as a string anywhere in the codebase?") for any candidate this ambiguous

For each remaining candidate, call jsat__blast_radius(target=<symbol>) to double-check
zero inbound impact (cross-verification against Phase 1, not a replacement for it).
CAVEAT: blast_radius's severity labels are heuristic and run hot — plain function
calls one hop away are routinely labeled "breaking" even when they're just a normal
call, not an actual risk. For this cross-check, only care about the *presence* of
a `CALLS`-type inbound edge (any caller at all), not the severity label attached to it.

Print: "🧹 Phase 2/3 — After exclusions: <N> confirmed unreferenced (<N> false positives removed)"

## Phase 3 — Report

Group by confidence:
  🔴 HIGH confidence dead code: no callers, not an entry point, not dynamically
     referenced, --include-private matched or is public API
  🟡 LOW confidence (verify manually before deleting): ambiguous dynamic-dispatch
     candidates that couldn't be fully ruled out in Phase 2

For each HIGH confidence item: file:line, symbol name, one-line reason it's safe to
remove (e.g. "superseded by X", "no import references found anywhere").

Print final summary:
  🧹 Dead code: <N> high-confidence, <N> low-confidence (needs manual check)
  💾 Estimated lines removable: <N>
  Top recommendation: <the single largest/safest removal to do first>

Do NOT delete anything automatically — this command reports, it does not modify code.
If the user wants deletions applied, that is a separate, explicit follow-up step.

## Learning from false positives (do this every run, not just on request)

The Phase 2 exclusion list is a fixed enumeration. It will never cover every
dynamic-dispatch shape in every codebase, so some HIGH confidence items WILL be
false positives — the same ones, repeatedly, if nothing records the correction.

Before Phase 1 runs, call jsat__knowledge_search(query="dead-code false positive
<path or --service scope>") to load any prior corrections for this scope, and treat
every symbol named in a hit as pre-excluded (report it under a new bucket
"⚪ PREVIOUSLY CONFIRMED LIVE (excluded by prior correction)" instead of re-flagging it).

Whenever the user responds to a reported HIGH confidence item with a correction
("no, that's used", "that's called via X", etc.) — whether in this turn or a
follow-up — call jsat__knowledge_add(text="DEAD-CODE FALSE POSITIVE: <symbol> in
<file> — reason: <what the user said, e.g. called via plugin registry / feature
flag / cron entrypoint> — scope: <path or --service>", category="dead-code-exclusion")
before doing anything else with that feedback. Without this, every future run of
this command repeats the identical false positive forever, which trains users to
stop trusting (and stop reading) the report.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct
report — interpret results in plain language. Do not echo raw JSON. Never claim a
symbol is dead code without having checked it against every exclusion pattern in
Phase 2; a false positive here means the user deletes code that's actually load-bearing.
