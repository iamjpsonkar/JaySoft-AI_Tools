---
description: Validate a database migration file for safety. Supports row count hints.
---

Parse $ARGUMENTS for optional flags, then call jsat__validate_migration:

Supported flags:
  --rows <table:N>[,<table:N>...]   → hint row count(s) for lock duration estimation.
                       Multiple tables may be given as a comma-separated list in a
                       single --rows (e.g. --rows orders:5000000,order_items:20000000).
                       A migration touching several large tables needs all of them
                       hinted, not just one — an unhinted table falls back to the
                       tool's default assumption, which can understate lock duration
                       on a table that's actually huge.
  (no flag)          → validate migration file at path=<rest>

If $ARGUMENTS has no path after stripping flags: stop and ask the user for the
migration file path rather than guessing one (e.g. the most recently modified file
under a migrations/ directory) — validating the wrong file and calling it safe is
worse than asking.

Examples:
  /jsat-migration db/migrations/0042_add_index.sql
    → jsat__validate_migration(path="db/migrations/0042_add_index.sql")

  /jsat-migration --rows orders:5000000 db/migrations/0042.sql
    → jsat__validate_migration(path="db/migrations/0042.sql", table_rows={"orders": 5000000})

  /jsat-migration --rows orders:5000000,order_items:20000000 db/migrations/0042.sql
    → jsat__validate_migration(path="db/migrations/0042.sql",
        table_rows={"orders": 5000000, "order_items": 20000000})

Show for each SQL operation: lock type, estimated duration, danger level.

For any dangerous operation, show the zero-downtime alternative EXACTLY as returned
by jsat__validate_migration — do not invent or improvise your own rewrite (e.g. a
"just add the column without a default" or "use pt-online-schema-change" suggestion
composed from general knowledge rather than the tool's output). An alternative that
sounds zero-downtime in the abstract can still take an ACCESS EXCLUSIVE lock or force
a full table rewrite on this specific engine/version; presenting an unverified
alternative as safe is itself a way to cause the outage this command exists to
prevent. If the tool did not return an alternative for a flagged operation, say so
explicitly instead of filling the gap yourself.

Flag: missing reversibility (a DOWN/rollback section for raw-SQL-style migrations, or
the framework's equivalent — e.g. a `downgrade()` in Alembic, a reverse migration in
Django/Rails — check which convention this repo's migration files actually use before
flagging it, since "no DOWN section" is a false positive for frameworks that express
rollback differently), multiple locking ops in single file, FK without index.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
