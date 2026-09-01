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

## Before mutating: size check and backup

This command REWRITES the on-disk graph store (`.jsat/graph/graph.db`, SQLite).
There is no built-in atomic-swap or auto-backup in the indexer — a crash, OOM, or
interrupt partway through a run can leave that file partially written or
inconsistent, and a `--force` re-index discards the incremental cache entirely
before anything new has been confirmed to succeed. Treat every index run as a
mutation that needs a rollback path, not a safe read:

  1. Size check FIRST — run `find <path> -type f | wc -l` via Bash before calling
     jsat__index_repo. If the count exceeds ~50,000 files, do NOT run one call
     over the whole tree — split by top-level directory instead (e.g.
     /jsat-index src/ then /jsat-index tests/ then /jsat-index lib/, one at a
     time) so a failure only affects one slice of the graph, not the whole index.
  2. Lock check FIRST — check for `.jsat/graph/.lock` (or equivalent lock/pid file
     if the indexer creates one) via Bash before calling jsat__index_repo. If it
     exists and its pid is still a live process, another /jsat-index run is
     already in progress: two concurrent indexers writing to the same SQLite file
     can race and corrupt it, and there is no documented tool-level guard against
     this. Stop and tell the user to wait for the other run (or confirm it's a
     stale lock from a crashed run before deleting it) rather than starting a
     second one blind.
  3. Corruption check FIRST, before an incremental run — if `.jsat/graph/graph.db`
     already exists, call jsat__get_index_status() BEFORE calling jsat__index_repo,
     not just after. An incremental index MERGES onto whatever is already on disk;
     if that call errors, times out, or returns nonsensical counts (e.g. negative,
     wildly inconsistent node/edge ratios), the existing graph is corrupted, not
     merely stale — do NOT run a plain incremental index onto it, since incremental
     mode has no integrity check of its own and will silently build new state on
     top of the corrupted base, propagating the corruption forward. Instead: back
     up the corrupted file anyway (for forensics), delete/rename `graph.db`, and
     run with `--force` (or equivalently a fresh full index) so the new graph is
     built from a clean base rather than merged onto a broken one. Tell the user
     explicitly that a corruption-triggered rebuild happened, not a routine index.
  4. Backup FIRST if `--force` was given, or if `.jsat/graph/graph.db` already
     exists and this is not a brand-new repo: `cp .jsat/graph/graph.db
     .jsat/graph/graph.db.bak` via Bash before calling jsat__index_repo. This is
     the only rollback path available if the run fails or the resulting graph
     looks corrupted.
  5. Run jsat__index_repo as specified above.
  6. Verify AFTER — call jsat__get_index_status() and sanity-check the result:
     node/edge counts should not have dropped to near-zero or become
     inconsistent (e.g. edges >> plausible for the node count) relative to the
     pre-run baseline. If the tool call errored, timed out mid-run, or the
     post-run status looks corrupted, restore the backup
     (`cp .jsat/graph/graph.db.bak .jsat/graph/graph.db`) and report the failure
     — do NOT report success on an index that was never actually verified.
  7. Only delete the `.bak` file once the new index has been confirmed sane.

After indexing, show: nodes indexed, edges indexed, files parsed vs skipped, parallel workers.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
