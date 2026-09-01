---
description: Reuse-first code planning — runs a 5-rung ladder against the graph before suggesting new code.
---

Before writing any new code, run the reuse ladder to find what already exists.
Rule: the best code is code you don't write. The graph index is the source of truth.

Parse $ARGUMENTS for optional flags:
  --audit   → scan a diff/file for over-engineering (code that reimplements existing)
  --review  → check a proposed implementation against the graph for duplication
  (no flag) → run the full reuse ladder for the given task description

## Reuse Ladder (run rungs in order — stop as soon as one finds a match)

RUNG 1 — Exact function/class match
  Extract the key function or class name implied by the task.
  Call: jsat__get_function(name=<key_term>)
  If found: do NOT immediately say "reuse this" — a name match only proves the
  symbol exists, not that it's safe/healthy to build on. Call
  jsat__blast_radius(target=<key_term>) as a live-health check before recommending
  it (this is the same inversion jsat-dead-code.md runs deliberately, just for one
  symbol instead of the whole codebase — reuse it here rather than re-deriving it):
    - If blast_radius shows zero inbound CALLS edges from anywhere else in the
      codebase, treat that as a signal the match may be exactly what
      jsat-dead-code.md would flag as unreferenced scaffolding, not a
      battle-tested utility — unless the symbol itself is an obvious entry point
      (main, a route handler, a CLI command), the same exclusions jsat-dead-code
      applies. In that case, say "⚠️ Found <name> at <file:line>, but it has no
      callers anywhere else in the codebase — verify it's not dead/unfinished code
      before reusing it" instead of an unqualified "✅ reuse this."
    - If the function's docstring/signature returned by get_function mentions
      deprecated/superseded/legacy, surface that verbatim rather than recommending
      reuse.
    - Only say the unqualified "✅ Already exists — reuse this" when the symbol
      has at least one real inbound caller and no deprecation signal — i.e. it is
      demonstrably live code, not merely present in the graph.

RUNG 2 — Similar pattern in the codebase
  Call: jsat__query(question="find existing implementation for: <task>")
  If the answer names specific functions/files: show them.
  Say "✅ Reuse this pattern from <file>:<line>."

  FALLBACK if jsat__query returns "[AI unavailable]" (a down/unconfigured AI
  provider takes the whole tool with it — this is common, not rare): do NOT
  treat this the same as "no match found" and silently fall through to Rung 3 —
  that would let a real duplicate slip past undetected, defeating the entire
  point of this reuse-first command. Instead substitute a keyword search via
  Bash (`grep -rn` for the task's key nouns/verbs across the codebase, or
  jsat__knowledge_search(query=<task>) for prior recorded decisions on the same
  area) and explicitly mark Rung 2's verdict as "UNVERIFIED (AI unavailable) —
  keyword search only" rather than "nothing found", so the final recommendation
  in Rung 5 is honest about what was and wasn't actually checked.

RUNG 3 — Existing service already handles this domain
  Call: jsat__list_services()
  Check if any service name matches the task domain.
  If found: say "✅ Delegate to <ServiceName> instead of building new."

RUNG 4 — Existing endpoint already exposes this
  Call: jsat__list_endpoints()
  Check if a route or method matches the needed operation.
  If found: say "✅ Call existing endpoint <METHOD> <route> instead."

RUNG 5 — Nothing found: minimum viable implementation
  Only reach this rung if rungs 1-4 all return empty. If Rung 2 was marked
  UNVERIFIED (AI unavailable) rather than a confirmed empty result, say so
  explicitly in the recommendation — e.g. "⚠️ Rung 2 could not be fully checked
  (AI unavailable); minimum implementation below, but re-run Rung 2 once the AI
  backend is back before treating this as confirmed non-duplicate."
  Suggest the minimum code:
  - One function, not a class
  - No abstraction layers
  - No config flags for hypothetical future use
  Say: "⚠️ Nothing found in codebase. Minimum implementation:" then show it.

## --audit flag
Given a diff or file path: scan for code that reimplements something already in the graph.
Call jsat__blast_radius(target=<path>) to find what already handles this area.
Call jsat__get_function for each new function name found in the diff.
Flag any that duplicate existing indexed functions.

## --review flag
Given a proposed implementation description: check each function/class name against the graph.
For each named entity: call jsat__get_function(name=<fn>) or jsat__get_class(name=<cls>).
Report: exists / not found / similar match (with location).


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
