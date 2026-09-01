---
description: Trace a call chain from a symbol through the codebase. Supports depth and direction.
---

CORRECTED MODEL — read before using: jsat__trace_call_chain is a POINT-TO-POINT
shortest-path finder. Its schema requires BOTH `from` and `to` (source and target
symbol/node) and returns the shortest BFS path between them, capped at a fixed
internal depth of 10 hops — there is no `symbol`-only mode and no configurable
`max_depth` parameter on this tool (an earlier version of this doc assumed both
existed; neither does — calling it with only a `symbol` arg or a `max_depth` arg
will fail schema validation).

Parse $ARGUMENTS for optional flags, then positional args: <source> [<target>].

Supported flags:
  --upstream         → find who calls <source> (see below — different tool, not
                        trace_call_chain, since there is no single target to trace to)
  (two positional args, <source> <target>)
                     → jsat__trace_call_chain(from=<source>, to=<target>) — find the
                        shortest call path connecting them
  (one positional arg, no --upstream)
                     → there is no tool that walks "everything <source> calls" with
                        no target. Use jsat__blast_radius(target=<source>) instead —
                        it reports downstream impact (not a pure call listing, and its
                        severity labels run hot: even an unremarkable one-hop call is
                        often labeled "breaking" — treat severity as a rough signal of
                        reach, not a literal breaking-change count).
                        SHAPE MISMATCH beyond severity noise: blast_radius is a
                        depth-limited BFS (default max_depth=5, overridable via
                        max_depth=<N>) over a mix of call AND import edges — it is
                        NOT the same shape as "everything X calls" would mean to a
                        user. Two concrete ways it diverges: (1) a real callee 6+
                        hops deep is silently absent from the result with no
                        "truncated" marker — it looks identical to "does not exist"
                        — so a clean/empty result at the default depth is NOT proof
                        of no reachability, only proof of no reachability within 5
                        hops; (2) import edges pull in files that merely import
                        <source>'s module without calling anything in it, so the
                        result over-includes relative to a pure call listing at the
                        same time it under-includes past depth 5. State both when
                        substituting blast_radius for a call trace, and re-run with
                        a higher max_depth if the user needs deep-chain coverage.

Examples:
  /jsat-trace PaymentService.process RefundService.issue
    → jsat__trace_call_chain(from="PaymentService.process", to="RefundService.issue")
      → shortest path between the two, up to 10 hops; {"found": false, ...} if none

  /jsat-trace --upstream PaymentService.process
    → jsat__get_consumers(target="PaymentService.process") — all callers of this
      symbol (capped at max_consumers=200 by default; pass a higher cap only if the
      default 200 is truncating real results, since a full-table scan on a large
      graph is the actual cost being guarded against)

  /jsat-trace PaymentService.process
    → jsat__blast_radius(target="PaymentService.process") — downstream reach, since
      no single-tool "callees of X" trace exists; call out this substitution to the
      user rather than presenting it as if it were a call-chain trace

Display the path/impact as a numbered chain from source to target (or source to each
impacted node). Show file:line for each node where the tool result provides it. If
jsat__trace_call_chain returns `{"found": false, ...}`, report that plainly — it means
no path exists within 10 hops, not that the tool failed. Neither trace_call_chain nor
get_consumers nor blast_radius calls the AI provider, so none of this degrades if the
AI backend is down.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
