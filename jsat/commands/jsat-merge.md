---
description: Merge a source branch into a target branch with graph-aware impact analysis, semantic conflict resolution, and post-merge verification.
---

Parse $ARGUMENTS for optional flags, then positional args: <source> <target>.

Supported flags:
  --dry-run          → run Phases 0-2 only (context + blast-radius + plan). Do NOT touch git state.
  --strategy ours|theirs|manual  → tie-breaker for PURELY NON-SEMANTIC conflicts only
                                    (lockfiles, generated files — see Phase 2). Never applies
                                    to logic conflicts; those always go through semantic
                                    resolution in Phase 3 regardless of this flag.
                                    (default: manual — regenerate/union, never blind-pick)
  --no-verify        → skip Phase 5 (test-gaps/review) after the merge — NOT recommended
  --continue         → resume a merge that is already in progress (working tree has an in-progress merge)
  --allow-dirty      → stash uncommitted changes before starting, restore after (Phase 0)
  (no flags)         → merge <source> into <target>, full flow

Examples:
  /jsat-merge feature/checkout-retry main
    → merge feature/checkout-retry into main, full flow

  /jsat-merge --dry-run feature/checkout-retry main
    → show impact + conflict plan only, no git mutation

  /jsat-merge --allow-dirty feature/checkout-retry main
    → stash WIP changes first, merge, then pop the stash back

  /jsat-merge --continue
    → resume an in-progress merge (conflict markers already in the tree)

NOTE ON TOOL USE: git itself is NOT an MCP-covered operation — there is no
`jsat__git_merge` tool. Use git via Bash for the mechanical merge/checkout/diff
steps. Use `jsat__*` MCP tools for everything analytical: impact, semantic
understanding of the codebase, test coverage, and review. Do not substitute
Bash/grep for the analytical steps below — that is exactly what the graph is for.

## Phase 0 — Preflight (git + graph context)

Run via Bash, in order:
  git status --porcelain
    → if dirty: refuse and stop UNLESS --continue or --allow-dirty was given.
      With --allow-dirty: `git stash push -u -m "jsat-merge autostash"` now; remember
      to `git stash pop` in Phase 6 regardless of success or failure (a failed merge
      must not silently lose the user's WIP).
  git rev-parse --verify <source>   → confirm source exists; stop with a clear error if not.
                                       If it fails but a remote-tracking ref exists
                                       (`git rev-parse --verify origin/<source>` or
                                       `upstream/<source>` succeeds), do NOT silently
                                       merge the remote ref under the local name — tell
                                       the user the local branch doesn't exist, ask
                                       whether to `git fetch` and create it
                                       (`git checkout -b <source> origin/<source>`) or
                                       whether they meant the fully-qualified
                                       `origin/<source>` / `upstream/<source>` as
                                       <source> instead. Multi-remote repos (origin vs
                                       upstream) make bare branch names ambiguous —
                                       never guess which remote was meant.
  git rev-parse --verify <target>   → confirm target exists; stop with a clear error if not
  git rev-parse --abbrev-ref HEAD   → capture the branch you started on, to restore on abort
  git checkout <target>             → REQUIRED. Never assume the user is already on <target> —
                                       merging without this checks out nothing and silently
                                       merges into whatever branch happened to be current.
  git log <target>..<source> --oneline   → commits that would be brought in
  git diff <target>...<source> --stat    → files touched, and how many

Call: jsat__get_index_status() and jsat__list_services() for CONTEXT_BRIEF (node/edge
counts, service names) — grounds every later step in what this repo actually is.

If --continue: skip straight to Phase 3 using `git diff --name-only --diff-filter=U`
to find already-conflicted files, with CONTEXT_BRIEF still gathered first.

## Fast-forward short-circuit (check before Phase 1)

Run via Bash: `git merge-base --is-ancestor <target> <source>` (exit code 0 means
target's tip is an ancestor of source — a pure fast-forward, zero conflict risk).

If fast-forward is possible AND no flags require the full analysis:
  Run: `git merge --ff-only <source>`
  Call: jsat__blast_radius_diff(diff=<git diff <target>@{1}...<target>>) once, for
    the user's awareness only — a breaking impact can still exist in a clean FF merge.
  Print: "⚡ Fast-forward merge — <N> commits, no conflicts possible. Blast radius: <summary>."
  Skip Phases 2-4 entirely (nothing to resolve or sanity-check that didn't already
  exist verbatim in <source>). Continue at Phase 5 for verification.

Otherwise continue to Phase 1.

Print: "🔍 Phase 0/6 — Preflight: <N> commits, <M> files changed, <K> services touched, FF-possible: <yes/no>"

## Phase 1 — Blast Radius (before touching anything)

Call: jsat__blast_radius_diff(diff=<output of `git diff <target>...<source>`>)
  (fallback: jsat__blast_radius(target=<most-changed file from Phase 0 stat>) per file
   if blast_radius_diff is unavailable or the diff is too large)

Group impacts by severity: breaking / degraded / warning / safe.
If any `breaking` impacts exist, print them explicitly and require the user to
acknowledge before proceeding (do not silently continue past a breaking result).

LARGE MERGE STRATEGY: if Phase 0's file-stat shows more than ~30 changed files or
the diff itself is too large for one blast_radius_diff call, split by top-level
directory/service and run blast_radius_diff once per group instead of one call for
the whole diff — same pattern as /jsat-review's large-diff strategy. Merge the
severity counts from each group before printing the Phase 1 summary.

Print: "💥 Phase 1/6 — Blast Radius: <N> breaking, <N> degraded, <N> warning, <N> safe"

## Phase 2 — Conflict Forecast + Plan (plan-first, not merge-first)

Run via Bash ONLY the non-mutating forecast — never start a real trial merge just to
detect conflicts, since that leaves the tree in a half-merged state if anything
interrupts the flow before the abort:
  `git merge-tree $(git merge-base <target> <source>) <target> <source>`
Parse its output for conflict markers to find which files WILL conflict, without
touching the working tree at all.

For each file that will conflict:
  Call: jsat__get_function / jsat__get_class / jsat__query(question="what does <file>
  do and who depends on it?") to understand the file's role before touching it.
  Classify the conflict type: imports, tests, lockfile/generated (package-lock.json,
  poetry.lock, Cargo.lock, *.snap, etc.), config, binary, logic,
  deleted-in-one-side-modified-in-other, submodule (gitlink), LFS-pointer.

  Two categories the classifier must not silently fold into "binary" or "logic":
    - submodule (gitlink): `git diff --name-only --diff-filter=U` includes
      conflicted submodules mixed in with normal files, but a submodule conflict
      is a disagreement about which COMMIT the pointer should reference, not file
      content — there is no line-level or semantic content to merge. Detect via
      `git ls-files --stage -- <file>` showing mode 160000. Resolution is: cd into
      the submodule, inspect which commit each side points to
      (`git log <target-sha>..<source-sha>` inside the submodule), pick or fast-
      forward to the correct commit, then `git add <submodule-path>` at the
      superproject level. --strategy ours/theirs may pick the pointer directly
      instead when the user just wants one side's version.
    - LFS-pointer files: text files whose tracked content is a pointer
      (`git show :2:<file>` / `:3:<file>` will show `version https://git-lfs...`
      stanzas, not real content) when `.gitattributes` marks the path as
      `filter=lfs`. Treat these like binary, NOT logic — a semantic/intent-based
      merge (Phase 3 step 2) is meaningless on a pointer blob; the only real
      choice is which side's LFS object wins, same as a binary conflict. Check
      `.gitattributes` for `filter=lfs` patterns before classifying any
      conflicted file as logic, since an LFS pointer's plain-text diff can look
      line-mergeable but isn't.

Build a resolution plan per file:
  - lockfiles / generated files → regenerate via the repo's own lock command, do not
    hand-merge; --strategy ours/theirs may pick which side's SOURCE deps win before
    regenerating, but the lockfile itself is always regenerated, never hand-edited
  - binary files → --strategy ours/theirs applies directly (there is no semantic
    middle ground for a binary); manual mode requires an explicit user choice
  - imports → union both sides, dedupe
  - tests → keep both sets of test cases unless they test the same removed behavior
  - config → merge keys; flag any key set differently by both sides for a human call
  - logic → requires semantic reasoning (Phase 3), not auto-resolution — --strategy
    NEVER short-circuits this category, regardless of what was passed
  - deleted-but-modified → surface explicitly, never silently pick a side
  - submodule (gitlink) → resolve at the commit-pointer level (see Phase 2's
    detection note), never as a content merge; surface the two candidate commits
    to the user if they diverge (neither is an ancestor of the other)
  - LFS-pointer → treat like binary: --strategy ours/theirs applies directly,
    manual mode requires an explicit user choice; never attempt semantic
    resolution on a pointer blob

Print the full per-file plan as: "📋 Phase 2/6 — Plan" before executing anything.
If --dry-run: STOP here. Do not run the fast-forward checkout mutation either if
--dry-run was combined with a would-be-FF merge — report "would fast-forward" instead.

## Phase 3 — Execute the Merge + Resolve Conflicts (semantic, not line-based)

Run via Bash: `git merge --no-ff <source>` (skip if already mid-merge via --continue).

For each conflicted file (`git diff --name-only --diff-filter=U`):
  1. Read both sides of the conflict (`git show :2:<file>` = target/ours,
     `git show :3:<file>` = source/theirs) plus the merge-base version (`git show :1:<file>`).
  2. Determine the INTENT behind each side's change (what problem was each side
     solving?), not just which lines differ — use jsat__query / jsat__get_function
     against the graph to check whether either side's change touches a function
     with callers elsewhere (i.e. whether one side's edit was itself a bug fix
     that the other side's edit would silently undo).
  3. Resolve by integrating both intents where possible, following the Phase 2 plan
     for that file's classified conflict type. Only apply --strategy ours/theirs
     for lockfile/generated/binary conflicts, per Phase 2's rule — never for logic.
  4. Remove conflict markers, stage the file (`git add <file>`).
  5. If a file was deleted on one side and modified on the other: surface this
     to the user explicitly — never resolve it silently.

Print progress per file: "⚙️ Phase 3/6 — Resolved <file> (<conflict type>)"

## Phase 4 — Syntax / Build Sanity Check

Run the repo's own lint/typecheck/build command if one is discoverable (check for
package.json scripts, Makefile, pyproject.toml, etc. via Bash) on the resolved files.
This is a mechanical sanity check, not a substitute for Phase 5.

Print: "🔧 Phase 4/6 — Sanity: <pass/fail>, <N> files checked"

## Phase 5 — Verify (skipped if --no-verify)

Call: jsat__get_test_gaps(path=<changed paths from Phase 0>) — flag any conflicted
file that now has an uncovered path introduced by the resolution.
Call: jsat__submit_for_review(diff=<git diff <target>..HEAD for the merge commit>)
  or jsat__get_high_confidence_bugs() if a review was already run this session.
Call: jsat__blast_radius(target=<target branch tip>, severity_filter=["breaking"])
  as a final breaking-change check now that the merge is actually applied.

Print: "🧪 Phase 5/6 — Verify: <N> test gaps, <N> confirmed bugs, <N> breaking (post-merge)"

## Phase 6 — Commit + Record

Run via Bash: `git commit --no-edit` (only if the merge left a commit pending —
`git merge --no-ff` usually opens the editor; use `--no-edit` to accept the default
merge message unless the user asked for a custom one).

If the commit fails because a pre-commit/commit-msg hook rejected it: report the
hook's exact output, fix what it flagged (or ask the user how to proceed), and
retry — do not bypass with `--no-verify` on the git commit itself unless the user
explicitly asks for that (this is git's own --no-verify, distinct from this
command's --no-verify flag which only skips Phase 5).

If --allow-dirty stashed changes in Phase 0: `git stash pop` now, whether the merge
succeeded or was aborted — the user's WIP must come back either way. If the pop
itself conflicts, surface that explicitly; do not silently drop the stash.

Call: jsat__knowledge_add(text="MERGE: <source> → <target> | Conflicts: <N files> |
Breaking: <yes/no> | Notable resolutions: <one-line per non-trivial conflict>",
category="decision") — only for merges that had real conflicts or breaking impacts;
skip this for trivial fast-forward merges.

Print final summary:
  ✅ Merged: <source> → <target>
  📁 Files with conflicts: <N> (<list>)
  💥 Breaking impacts: <N> (pre-merge) → <N> (post-merge)
  🧪 Test gaps introduced: <N>
  📝 Decision logged: <yes/no>
  Rollback (not yet pushed): `git reset --hard ORIG_HEAD`
  Rollback (already pushed): `git revert -m 1 <merge-commit-sha>` — reset --hard is
    unsafe once others may have pulled the merge commit.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually perform the phases described above (git via Bash, analysis
via jsat__* MCP tools), then reply with a direct, useful summary — interpret results
in plain language. Do not merely describe what the tool does, and do not echo raw
JSON. Never silently resolve a breaking or deleted-vs-modified conflict — always
surface it to the user before finalizing. Never leave the tree in a half-merged or
half-stashed state — every mutating step in Phase 0 has a matching cleanup in
Phase 6 regardless of whether the merge itself succeeds.
