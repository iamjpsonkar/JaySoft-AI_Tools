---
description: Decision journal — log architectural decisions and surface them by file, topic, or blast-radius context.
---

Architectural decision journal. Log decisions with context; retrieve them when analyzing impact or planning changes.

Parse $ARGUMENTS for optional subcommand:
  log <text>               → store a decision
  log --impact h|m|l <text> → store with impact rating (high/medium/low)
  list                     → show all decisions (recent first)
  list <category>          → filter by category
  search <query>           → semantic search across decisions
  context <file_or_symbol> → show decisions relevant to this file or function
  (no subcommand)          → same as search <rest>

## log subcommand
Store the decision in the knowledge base with structured context:
Call: jsat__knowledge_add(
  text="DECISION: <text> | Impact: <impact> | Date: today",
  category="decision"
)
Confirm with ID and 1-line preview.

## context subcommand
Find decisions relevant to a file or function:
  Call: jsat__blast_radius(target=<file_or_symbol>) to find connected nodes
  Call: jsat__knowledge_search(query="decision related to <file_or_symbol>")
  Show decisions whose scope overlaps with the blast-radius output.

## search subcommand
  Call: jsat__knowledge_search(query=<query>)
  Show matching decisions with date, impact, and text.

## list subcommand
  Call: jsat__knowledge_list(category="decision")
  Show all decisions sorted by recency.

Examples:
  /jsat decide log Switched caching from Redis to in-memory — cost $500/month, latency acceptable
  /jsat decide log --impact h Chose PostgreSQL over MongoDB for ACID compliance on payment records
  /jsat decide context src/payments/service.py
  /jsat decide search caching strategy

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
