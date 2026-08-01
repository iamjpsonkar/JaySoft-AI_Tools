---
description: Query or manage the JSAT knowledge base. Supports subcommands in $ARGUMENTS.
---

Parse $ARGUMENTS for an optional subcommand, then call the right tool:

Subcommands:
  add <text>                  → call jsat__knowledge_add with text=<text>
  add --category <cat> <text> → store with category (adr, runbook, pattern, decision)
  list                        → call jsat__knowledge_list to show all entries
  list <category>             → call jsat__knowledge_list with category=<category>
  stale <id>                  → call jsat__knowledge_flag_stale with entry_id=<id>
  search <text>               → call jsat__knowledge_search with query=<text>
  (no subcommand)             → call jsat__knowledge_query with query=<rest>  (semantic search)

Examples:
  /jsat-knowledge what are the payment service ADRs?
    → jsat__knowledge_query(query="what are the payment service ADRs?")

  /jsat-knowledge add Use tenacity for all retry logic per ADR-007
    → jsat__knowledge_add(text="Use tenacity for all retry logic per ADR-007")

  /jsat-knowledge add --category adr Payments use idempotency keys for all mutations
    → jsat__knowledge_add(text="...", category="adr")

  /jsat-knowledge list adr
    → jsat__knowledge_list(category="adr")

  /jsat-knowledge search retry patterns
    → jsat__knowledge_search(query="retry patterns")


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
