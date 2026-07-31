---
description: Add an entry to the JSAT knowledge base with optional category.
---

Parse $ARGUMENTS for optional --category flag, then call jsat__knowledge_add:

  --category <cat>  → tag the entry (adr, runbook, pattern, decision, context)
  (no flag)         → store with no category

Examples:
  /jsat-knowledge-add Use tenacity for retry logic per ADR-007
    → jsat__knowledge_add(text="Use tenacity for retry logic per ADR-007")

  /jsat-knowledge-add --category adr All payment mutations require idempotency keys
    → jsat__knowledge_add(text="All payment mutations require idempotency keys", category="adr")

Confirm the entry was stored: show its ID and a one-line preview.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
