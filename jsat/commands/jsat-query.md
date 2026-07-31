---
description: Answer a question about this codebase using JSAT's graph index. Supports service scoping.
---

Parse $ARGUMENTS for optional flags, then call jsat__query:

Supported flags:
  --service <name>  → scope answer to one service (reduces context, avoids timeout)
  --short           → prepend brevity constraint (≤3 sentences)
  (no flag)         → full graph query

Examples:
  /jsat-query what does the payment service do?
    → jsat__query(question="what does the payment service do?")

  /jsat-query --service PaymentService how is retry handled?
    → jsat__query(question="how is retry handled?", service="PaymentService")

TIMEOUT RECOVERY: If jsat__query times out or returns "[AI unavailable]":
  1. Narrow scope: add --service <name> to limit context
  2. Use /jsat-short for a briefer answer (≤3 sentences)
  3. Break complex questions into smaller focused queries

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
