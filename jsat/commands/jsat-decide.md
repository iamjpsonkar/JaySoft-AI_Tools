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
  (no subcommand, with text)      → same as search <rest>
  (no subcommand, no text at all) → same as list (an empty search query is
                                     meaningless; showing everything is more
                                     useful than a null-query search)

## log subcommand
Store the decision in the knowledge base with structured context. Resolve <impact>
to "high"/"medium"/"low" from --impact h|m|l if given, else "unspecified" — never
leave a raw unresolved placeholder in stored data. Resolve <date> to the actual
current date (e.g. via `date +%Y-%m-%d` over Bash, or the session's current date)
— never store the literal word "today", since that string is meaningless once
read back days or weeks later.

BEFORE storing, check whether this decision reverses or replaces an earlier one on
the same topic — otherwise `search`/`list` will surface both the old and new
decision with no way to tell which is current, and a reader (including a future
you, in a different session) may act on the superseded one:
  Call jsat__knowledge_search(query=<text>) and inspect hits already tagged
  category="decision". If a prior decision clearly covers the same topic/component
  and this new one changes or reverses it (judge from the text — do not require an
  exact topic-string match), treat it as a supersession:
    1. Call jsat__knowledge_flag_stale(entry_id=<old decision's ID>) — note this
       tool only marks staleness, it has no "reason" or "superseded_by" field, so
       the link itself must be recorded in the new entry's TEXT (next step) or the
       relationship is lost.
    2. Store the new decision with an explicit backlink so `search`/`list`/`context`
       can render the chain even though the underlying tool can't link entries:
       text="DECISION: <text> | Impact: <impact|unspecified> | Date: <actual
       YYYY-MM-DD> | Supersedes: <old decision ID> (<old decision's one-line text>)"
    3. Tell the user explicitly: "This supersedes decision <old ID> (<old text>) —
       flagged it stale." Do not silently flag without surfacing it — a decision
       journal that quietly rewrites history is worse than one that never notices.
  If no prior decision matches, store normally:
Call: jsat__knowledge_add(
  text="DECISION: <text> | Impact: <impact|unspecified> | Date: <actual YYYY-MM-DD>",
  category="decision"
)
Confirm with ID and 1-line preview.

## context subcommand
Find decisions relevant to a file or function:
  Call: jsat__blast_radius(target=<file_or_symbol>) to find connected nodes
  Call: jsat__knowledge_search(query="decision related to <file_or_symbol>")
  Show decisions whose scope overlaps with the blast-radius output. Apply the same
  supersession marking as search/list (below) — "context" is used to justify a
  change against past decisions, so surfacing a reversed decision as if it were
  still active is the single worst place for this gap to bite.

## search subcommand
  Call: jsat__knowledge_search(query=<query>)
  Show matching decisions with date, impact, and text. If a returned decision's
  text contains "Supersedes: <ID>", or its own ID is referenced as superseded by
  ANOTHER hit in the same result set, mark it "⚠️ SUPERSEDED — see <newer ID>"
  instead of presenting it at equal weight with the current decision. Do not rely
  on knowledge_flag_stale's internal state to convey this — it carries no reason
  or link, so the "Supersedes:" text marker written at log time is the only
  reliable signal; cross-reference results against each other for it.

## list subcommand
  If a <category> argument was given after "list", call:
    jsat__knowledge_list(category=<category>)
  Otherwise (bare "list", or no subcommand + no text — see above) default to the
  decision journal's own scope:
    jsat__knowledge_list(category="decision")
  Do NOT hardcode category="decision" unconditionally — that silently ignores the
  user-supplied filter documented above ("list <category> → filter by category")
  and ignores/masks the empty-args-defaults-to-list behavior described above too.
  Show all decisions sorted by recency. Apply the same supersession marking as the
  search subcommand above (scan text for "Supersedes:" backlinks across the listed
  set) — a "recent first" list is exactly where a superseded decision looks most
  current if it isn't flagged, since its neighbors are unrelated topics, not its
  replacement.

Examples:
  /jsat decide log Switched caching from Redis to in-memory — cost $500/month, latency acceptable
  /jsat decide log --impact h Chose PostgreSQL over MongoDB for ACID compliance on payment records
  /jsat decide context src/payments/service.py
  /jsat decide search caching strategy


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
