---
description: List all API endpoints found in the indexed codebase. Supports filtering.
---

Parse $ARGUMENTS for optional flags, then call jsat__list_endpoints:

  --service <name>    → filter to one service's endpoints
  --method <METHOD>   → filter by HTTP method (GET, POST, PUT, PATCH, DELETE)
  (no flag)           → list all endpoints

Show each endpoint: HTTP method, route, handler function, auth required (yes/no).
Group by service. Show total count. Highlight unauthenticated endpoints with ⚠️.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
