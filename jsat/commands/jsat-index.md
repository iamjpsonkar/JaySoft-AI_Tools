---
description: Build or refresh the JSAT codebase graph index. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call jsat__index_repo:

Supported flags (strip from path before passing):
  --force          → pass force=true  (full re-index, ignores incremental cache)
  --languages X,Y  → pass languages=["X","Y"]  (limit to specific languages)
  (no flag)        → incremental index of path (or "." if empty)

Examples:
  /jsat-index .                    → jsat__index_repo(path=".")
  /jsat-index src/ --force         → jsat__index_repo(path="src/", force=true)
  /jsat-index . --languages python,go  → jsat__index_repo(path=".", languages=["python","go"])

After indexing, show: nodes indexed, edges indexed, files parsed vs skipped, parallel workers.
For large repos (>50k files): index one directory at a time — /jsat-index src/ then /jsat-index tests/

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
