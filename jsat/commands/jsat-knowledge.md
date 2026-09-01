---
description: Query or manage the JSAT knowledge base. Supports subcommands in $ARGUMENTS.
---

Parse $ARGUMENTS for an optional subcommand, then call the right tool:

Subcommands:
  add <text>                  → call jsat__knowledge_add with text=<text>
  add --category <cat> <text> → store with category (adr, runbook, pattern, decision)

  For `add`: confirm using the tool's ACTUAL return value — it responds with only
  "Stored in knowledge base (category: <category>)", it does NOT return an entry
  ID. The real ID is a deterministic sha256 hash of category+text computed
  internally; do not invent or guess a look-alike ID (that would be a
  hallucination). Instead echo back the category and a one-line preview of the
  text supplied (truncate long text with "…"), e.g. "Stored (category: adr):
  'All payment mutations require idempotency keys'". If the user needs the
  entry's ID later (e.g. to flag it stale), point them at jsat__knowledge_search
  or jsat__knowledge_list to look it up rather than assuming one.
  list                        → call jsat__knowledge_list to show all entries
  list <category>             → call jsat__knowledge_list with category=<category>
  stale <id>                  → call jsat__knowledge_flag_stale with entry_id=<id>.
                                 IDs are not shown anywhere in normal output (`add`
                                 deliberately doesn't echo one — see below), so a
                                 user typing `stale <id>` is almost always pasting a
                                 guessed or half-remembered value. If the tool
                                 returns a not-found/no-op result (or any response
                                 that doesn't clearly confirm the entry was flagged),
                                 do NOT report success — say the ID wasn't found and
                                 run jsat__knowledge_search(query=<best guess at the
                                 entry's content, if the user gave one>) or
                                 jsat__knowledge_list() to help them find the real ID
                                 before retrying.
  search <text>               → call jsat__knowledge_search with query=<text>
  (no subcommand)             → call jsat__knowledge_query with question=<rest>  (semantic search)

PARAMETER NAME: jsat__knowledge_query's required argument is `question`, not
`query` — do not confuse it with jsat__knowledge_search, whose required argument
really is `query`. Passing `query=` to knowledge_query fails schema validation
(question is required and would be missing).

jsat__knowledge_query synthesizes its answer with an LLM call (same class of
dependency as jsat__query) and degrades to a "[No AI provider ...]" message when
no AI backend is configured — a known, common failure mode, not rare. FALLBACK
if that happens: call jsat__knowledge_search(query=<rest>) instead — search only
optionally reranks with AI (skipped gracefully when none is configured) and
still returns real keyword/graph-matched entries without it. Label results from
this path "AI-unavailable — raw search matches, not a synthesized answer" so the
user knows it's a narrower, unranked substitute for what they asked for.

Examples:
  /jsat-knowledge what are the payment service ADRs?
    → jsat__knowledge_query(question="what are the payment service ADRs?")

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
