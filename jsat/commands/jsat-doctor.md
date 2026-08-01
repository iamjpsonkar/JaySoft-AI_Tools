---
description: Run a full JSAT system health check.
---

Use jsat__health to run a full system check. Present results in this order:
1. JSAT version and graph backend
2. AI provider: which is active, which are available, free vs paid
3. Graph: node count, edge count, last indexed timestamp
4. MCP connection: which tools are loaded
5. Config: profile (solo/team/ci), any missing settings

Flag as ⚠️ WARN: graph not indexed, no AI configured, stale index (>7 days old)
Flag as ❌ ERROR: graph backend unavailable, AI provider failing test call
For each issue: suggest the fix command (e.g. /jsat-index ., jsat ai use ollama).


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
