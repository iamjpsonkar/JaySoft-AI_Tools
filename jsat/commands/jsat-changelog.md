---
description: Generate a changelog between two refs, grouped by service and impact, from commit history and the graph.
---

Parse $ARGUMENTS for optional flags, then positional args: [from] [to] (defaults to
the last tag and HEAD, or main and HEAD if no tags exist).

Supported flags:
  --service <name>   → scope to one service's changes only
  --breaking-only    → show only changes with a breaking blast-radius impact

Examples:
  /jsat-changelog
    → changelog since the last tag
  /jsat-changelog v1.2.0 v1.3.0
    → changelog between two tags
  /jsat-changelog --service PaymentService main HEAD

## Phase 1 — Gather

PREFLIGHT: if <from> and/or <to> were given explicitly, verify each ref actually
exists before using it (`git rev-parse --verify <ref>`) — do not let a typo'd tag or
branch name silently fall through to a git error mid-command, or worse, to `git log`
treating it as a pathspec and returning an empty-but-not-obviously-wrong range. Stop
with a clear error naming which ref failed to resolve.

Run via Bash: `git log <from>..<to> --oneline --no-merges` if <from>/<to> given, else
`git describe --tags --abbrev=0` to find the last tag, then log from there to HEAD
(also with `--no-merges`). Excluding merge commits avoids double-counting: a merge
commit's own log entry does not add new file changes beyond what its individual
commits already contributed, and classifying it separately would duplicate entries
already covered by those commits (or, worse, misclassify a merge as its own
"feature"/"fix" using only the merge commit's message).
Treat this git log as the authoritative, exact commit list for the range — it is
the only source here that is bound to actual refs.

LARGE-RANGE STRATEGY: if the commit count exceeds ~100, do not run per-commit
`git diff --stat` and (for --breaking-only) per-commit jsat__blast_radius_diff calls
against the full unscoped list one at a time — first group commits by the services
their paths touch (one `git diff --stat` pass per commit is still needed to build
that grouping, but the expensive step is the per-commit blast-radius call), then
run the breaking-change check service-by-service, same chunking rationale as
/jsat-merge and /jsat-blast-radius use for large diffs. Note in Phase 1's printed
line when this path was taken so the user knows the breaking-change flags are from
a chunked pass, not a single exhaustive one.

jsat__get_recent_changes does NOT take a `target` or `service` (singular) parameter
— its real signature is `services: [<name>, ...]` (array) and `since: "<duration>"`
(e.g. "72h", default), a rolling time window, not an arbitrary git ref range. It
CANNOT be pointed at `<from>..<to>` precisely, so do not rely on it to bound or
replace the git log above. Use it only as best-effort supplementary color:
  - If --service was given: jsat__get_recent_changes(services=[<name>]) with the
    default `since` window, and only treat its output as directional context
    (e.g. "recent deploys around this time") — not as the enriched commit list.
  - If the requested range is older than the rolling window would cover, skip this
    call entirely rather than presenting a mismatched/misleading partial result.
Unless scoped by --service: call jsat__list_services() to group commits by which
  service's files they touched (via `git diff --stat` per commit, not via
  get_recent_changes).

Print: "🔍 Phase 1/2 — Gathered: <N> commits across <N> services"

## Phase 2 — Classify + Compose

For each commit, classify by conventional-commit prefix if present (feat/fix/docs/
refactor/chore). Only when no prefix is present, infer from the diff shape using
concrete signals, in this priority order — do not guess free-form:
  1. Touches only test files (`test_*`, `*_test.*`, `*.spec.*`, `__tests__/`) → chore (tests)
  2. Touches only docs/markdown/comments → docs
  3. Net change is new files/new functions with no deletions to existing public
     signatures → Added
  4. Modifies an existing function body without changing its signature, in a file
     that already has a prior version in history → Fixed if the commit message or
     diff mentions an error/bug-shaped condition (null check, exception, off-by-one,
     wrong comparison), else Changed
  5. Removes files/functions/endpoints → Changed (or Breaking — let the Phase 2
     blast-radius check decide breaking status; do not assume removal == breaking)
  6. None of the above match clearly → Changed (the safe default; never fabricate
     "Added" or "Fixed" for a diff shape that doesn't clearly support it)
Group output by service, then by category within each service.

If --breaking-only or to flag breaking changes regardless: call
jsat__blast_radius_diff(diff=<per-commit diff>) for commits touching shared/core
files (skip this for purely additive/docs commits — don't spend budget classifying
changes that can't be breaking).

Compose:

  # Changelog: <from> → <to>

  ## <ServiceName>
  ### Breaking
  - <commit summary> (<short-hash>) — <what breaks and for whom>
  ### Added
  - <commit summary> (<short-hash>)
  ### Fixed
  - <commit summary> (<short-hash>)
  ### Changed
  - <commit summary> (<short-hash>)

  (repeat per service; omit empty categories and empty services)

Print the composed changelog as the final output — this IS the deliverable.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then output the
composed changelog in full — that is the final answer. Never invent a commit or
a breaking-change claim not backed by git log / blast_radius output.
