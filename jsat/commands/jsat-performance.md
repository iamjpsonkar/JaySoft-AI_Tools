---
description: Profile the hot paths that matter — find the highest-traffic, highest-complexity functions, measure them, and fix the ones users actually wait on.
---

Parse $ARGUMENTS for the focus of the profile: a service, a path, or "hot" to let the
graph pick.

Supported flags:
  --service <name> → scope to one service (avoids timeout on large codebases)
  --top <N>        → focus on the top N candidates (default 10)
  --dry-run        → report candidates and a fix plan only; do not modify code

Examples:
  /jsat-performance --top 5 payments.py
    → the 5 most-likely hot functions in payments.py, with a fix plan
  /jsat-performance --service svc_users
    → the hottest paths in the users service

THIS IS NOT A NEW MCP CAPABILITY: it ranks existing graph data (complexity, call
depth, fan-out), then fixes the ranked winners — no profiling agent, no flamegraph.

## Phase 1 — Rank by graph data

Call: jsat__query(question="list the functions in <scope> with the highest cyclomatic
complexity and most calls to other functions, with their file paths") — the graph
stores complexity and call edges, so this is a lookup, not inference. Also call
jsat__get_test_gaps(path=<scope>) in the same pass: an untested hot function is both
a risk (no guard) and an opportunity (safe to touch).
Rank candidates by (fan-out × complexity), take the top N.
Print: "📊 Phase 1/3 — ranked <N> candidates by complexity × fan-out"

## Phase 2 — Read the code, hypothesise the cost

For each candidate, read the function body (jsat__get_function(name=...)) and state a
one-line cost hypothesis BEFORE suggesting a fix: algorithmic (nested loop over a
growing list), repeated work (same lookup per item that could be hoisted), I/O
(N+1 calls, sync calls in a loop), or allocation. Trace the locals with
jsat__trace_call_chain(from=<caller>, to=<candidate>) to see how deep the call sits
under user-facing endpoints — a hot util two hops under a request endpoint matters
more than the same util in a batch script.
Group candidates: 🔥 hot (deep + high complexity), 🌋 hidden (deep but low complexity —
the classic N+1 / repeated-query class), ❄️ cold (high complexity, no real path — skip).
Print: "🔬 Phase 2/3 — hypothesis per candidate; <N> hot, <M> hidden, <K> cold"

## Phase 3 — Fix the 🔥 and 🌋 winners, nothing else

For each winner, propose the minimal fix and its expected effect:
  - hoist the repeated work out of the loop
  - replace O(n²) with the obvious data structure
  - batch the N+1 calls
  - memoise / cache the repeated computation (name the cache key)
Each fix must state a measurable success criterion (e.g. "one <endpoint> call no longer
re-queries per item — halves the query count"). Apply fixes ONLY to the 🔥/🌋
winners; ❄️ cold complexity is real future tax but not today's latency — report it,
do not touch it. In --dry-run mode produce the fix list and stop; otherwise apply the
fixes as separate commits and re-run Phase 1 ranking so the before/after is visible.

Print final summary:
  ⚡ <endpoint or top function> was <cost hypothesis>; fix = <one line>; expected <effect>
  Cold-but-complex (not touched): <list>

Do NOT rewrite shared public API signatures as a "performance fix" — a signature
change is a refactor (see /jsat-refactor) and needs its own blast-radius pass.

## Learning from the run

Call jsat__knowledge_add(
  text="PERF <scope or endpoint>: <function> was <hypothesis>, fixed by <fix>, expected <effect>",
  category="performance")
so a future run does not re-flag the same function.

BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Run Phase 1 with a real jsat__query over the indexed graph — do not
hand-pick functions by reading the tree. Every fix must be tied to a measured-ish cost
hypothesis from Phase 2; "this looks slow" is not a reason. Never apply fixes in
--dry-run mode. Never change a public signature inside a performance pass.