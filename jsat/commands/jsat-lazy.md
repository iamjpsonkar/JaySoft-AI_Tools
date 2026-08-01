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
  If found: show file:line, signature, and say "✅ Already exists — reuse this."

RUNG 2 — Similar pattern in the codebase
  Call: jsat__query(question="find existing implementation for: <task>")
  If the answer names specific functions/files: show them.
  Say "✅ Reuse this pattern from <file>:<line>."

RUNG 3 — Existing service already handles this domain
  Call: jsat__list_services()
  Check if any service name matches the task domain.
  If found: say "✅ Delegate to <ServiceName> instead of building new."

RUNG 4 — Existing endpoint already exposes this
  Call: jsat__list_endpoints()
  Check if a route or method matches the needed operation.
  If found: say "✅ Call existing endpoint <METHOD> <route> instead."

RUNG 5 — Nothing found: minimum viable implementation
  Only reach this rung if rungs 1-4 all return empty.
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
