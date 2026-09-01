---
description: List all API endpoints found in the indexed codebase. Supports filtering.
---

Parse $ARGUMENTS for optional flags, then call jsat__list_endpoints:

  --service <name>    → filter to one service's endpoints
  --method <METHOD>   → filter by HTTP method (GET, POST, PUT, PATCH, DELETE)
  (no flag)           → list all endpoints

Show each endpoint: HTTP method, route, handler function, auth required (yes/no).
Group by service. Show total count. Highlight unauthenticated endpoints with ⚠️.

Auth detection is static-analysis-derived, not runtime-verified — treat the field
as three states, not two, even if the tool only returns yes/no: a confirmed "no"
(no auth decorator/middleware found on a resolvable handler) is a real finding;
but for handlers whose auth is applied dynamically (middleware registered by
string/config, base-class-inherited auth the analyzer didn't resolve, auth checked
inside the handler body rather than via decorator), the analyzer may also report
"no" despite auth actually being enforced. Do not present every "no" with the same
confidence: if the handler function's own body (via jsat__get_function on the
handler) shows no auth-related calls AND no decorator, call it a confirmed ⚠️
gap; if you can't independently corroborate it (function body not resolvable,
inherited from an unindexed base, etc.), still flag it but label it "⚠️ unauthenticated
(unverified — confirm manually)" rather than asserting it as a definite gap, so
the user doesn't file a false security finding off a static-analysis blind spot.

If --service <name> was given and it does not match any indexed service, say so
explicitly (list the actual indexed service names from the result, if any come back)
rather than silently showing zero endpoints as if the filter matched nothing real —
those are two different failure modes and the user needs to know which one happened.

If the result is empty with no filter applied: suggest `jsat index .` (the graph may
be empty or stale) before assuming the repo genuinely has no endpoints.

This tool is pure graph lookup (no LLM backend involved), so it does not degrade when
an AI provider is down — no fallback needed here.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
