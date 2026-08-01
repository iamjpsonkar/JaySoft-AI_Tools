---
description: Show recent changes in the codebase. Supports time range and author filters.
---

Parse $ARGUMENTS for optional flags, then call jsat__get_recent_changes:

Supported flags:
  --since <time>    → limit to changes since (24h, 7d, 30d)
  --author <name>   → filter by commit author name (substring match)
  --service <name>  → scope to one service's files
  (no flag)         → recent changes for target=<rest or ".">

Examples:
  /jsat-recent
    → jsat__get_recent_changes(target=".")

  /jsat-recent --since 24h src/payment/
    → recent changes in src/payment/ in the last 24 hours

  /jsat-recent --author jay
    → commits by any author whose name contains "jay"

Show: short hash, author, timestamp, files changed, summary.
Highlight: large commits (>10 files), changes touching auth/payment/migrations.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
