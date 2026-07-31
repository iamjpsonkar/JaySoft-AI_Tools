---
description: Validate a database migration file for safety. Supports row count hints.
---

Parse $ARGUMENTS for optional flags, then call jsat__validate_migration:

Supported flags:
  --rows <table:N>   → hint table row count for lock duration estimation
                       (e.g. --rows orders:5000000)
  (no flag)          → validate migration file at path=<rest>

Examples:
  /jsat-migration db/migrations/0042_add_index.sql
    → jsat__validate_migration(path="db/migrations/0042_add_index.sql")

  /jsat-migration --rows orders:5000000 db/migrations/0042.sql
    → jsat__validate_migration(path="db/migrations/0042.sql", table_rows={"orders": 5000000})

Show for each SQL operation: lock type, estimated duration, danger level.
Show zero-downtime alternative for any dangerous operation.
Flag: missing rollback (DOWN section), multiple locking ops in single file, FK without index.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
