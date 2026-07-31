---
description: List all API endpoints found in the indexed codebase. Supports filtering.
---

Parse $ARGUMENTS for optional flags, then call jsat__list_endpoints:

  --service <name>    → filter to one service's endpoints
  --method <METHOD>   → filter by HTTP method (GET, POST, PUT, PATCH, DELETE)
  (no flag)           → list all endpoints

Show each endpoint: HTTP method, route, handler function, auth required (yes/no).
Group by service. Show total count. Highlight unauthenticated endpoints with ⚠️.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
