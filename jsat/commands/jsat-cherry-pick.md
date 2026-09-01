---
description: Cherry-pick a single commit onto the current branch with graph-aware impact analysis and semantic conflict resolution.
---

Parse $ARGUMENTS for optional flags, then positional arg: <commit> (hash or ref).

Supported flags:
  --dry-run      → show impact + conflict forecast only, do NOT touch git state
  --continue     → resume a cherry-pick already in progress
  --abort        → run `git cherry-pick --abort` and stop
  --allow-dirty  → stash uncommitted changes before starting, restore after (Phase 0)
  (no flags)     → cherry-pick <commit> onto the current branch, full flow

Examples:
  /jsat-cherry-pick a1b2c3d
  /jsat-cherry-pick --dry-run a1b2c3d

Single-commit sibling of `/jsat-merge` and `/jsat-rebase` — same semantic conflict
resolution engine, applied to exactly one commit.

NOTE ON TOOL USE: git itself has no MCP tool — use Bash for the mechanical
cherry-pick/diff steps. Use jsat__* MCP tools for all impact/semantic analysis.

## Phase 0 — Preflight

Run via Bash, in order:
  git status --porcelain
    → if dirty: refuse and stop UNLESS --continue, --abort, or --allow-dirty was given.
      With --allow-dirty: `git stash push -u -m "jsat-cherry-pick autostash"` now;
      remember to `git stash pop` in Phase 3 regardless of success or failure.
  git rev-parse --verify <commit>   → confirm the commit/ref exists; stop with a
                                       clear error if not
  git rev-parse --abbrev-ref HEAD   → print the current branch explicitly. Cherry-pick
                                       never switches branches — it applies onto
                                       whatever is currently checked out — so surface
                                       this up front rather than silently picking onto
                                       the wrong branch because the user assumed one.
  git merge-base --is-ancestor <commit> HEAD
    → if exit code 0, <commit> (or an equivalent change) is already in this branch's
      history; warn the user explicitly and ask before proceeding (cherry-picking an
      already-applied commit either no-ops or produces a confusing duplicate diff).
  git show --stat <commit>          → files this commit touches
Call: jsat__get_index_status() and jsat__list_services() for context.

If --abort: `git cherry-pick --abort`, confirm, stop.
If --continue: skip to Phase 2 using `git diff --name-only --diff-filter=U`.

Print: "🔍 Phase 0/4 — Preflight: <commit> onto <current branch>, <N> files touched"

## Phase 1 — Blast Radius + Conflict Forecast

Call: jsat__blast_radius_diff(diff=<git show <commit>>) — same severity grouping
as /jsat-merge Phase 1 (group by breaking/degraded/warning/safe; there is no
`severity_filter` tool parameter — filter the returned list yourself). Require
acknowledgment of any breaking impact.

Conflict forecast (non-mutating — never run the real cherry-pick twice just to
detect conflicts, per the same reasoning as /jsat-merge's merge-tree fix):
  if <commit> has exactly one parent:
    `git merge-tree <commit>^1 HEAD <commit>` — 3-way forecast using the commit's
    own parent as the merge base. Parse for conflict markers to see which files
    WILL conflict, without touching the working tree.
  if <commit> is a merge commit (multiple parents):
    skip the automated forecast — `-m <mainline>` is needed and ambiguous to infer
    automatically; note in the printed plan that conflict risk is unknown until
    the pick is actually attempted. Record this fact (merge commit, mainline
    unresolved) for Phase 2 — `git cherry-pick <commit>` on a merge commit fails
    outright without `-m`, so Phase 2 MUST ask the user which parent number is
    mainline (`git show <commit>` to list parents in order, mainline is usually 1
    for a commit merged into the branch being picked from) before attempting the
    pick; never attempt a bare `git cherry-pick <merge-commit>` expecting it to work.

Print: "💥 Phase 1/4 — Blast Radius: <N> breaking / <N> degraded / <N> warning / <N> safe.
Forecast: <N> files will conflict (or 'unknown — merge commit')"

If --dry-run: STOP here after printing the forecast. Do not run Phase 2.

## Phase 2 — Cherry-pick + resolve

Run via Bash: `git cherry-pick <commit>` (or, if Phase 1 flagged <commit> as a merge
commit, `git cherry-pick -m <mainline> <commit>` using the mainline number confirmed
with the user) (or `--continue` if resuming).

If it conflicts:
  1. Read both sides (`git show :2:<file>`, `git show :3:<file>`, `git show :1:<file>`).
  2. Determine intent per side via jsat__query/jsat__get_function — same semantic
     approach as /jsat-merge Phase 3.
  3. Resolve, `git add <file>`, `git cherry-pick --continue`.
  4. Never silently resolve a deleted-vs-modified conflict — surface it.
  5. If the resulting commit is rejected by a pre-commit/commit-msg hook: report the
     hook's exact output, fix what it flagged (or ask the user how to proceed), and
     retry — do not bypass with git's own `--no-verify` unless the user explicitly
     asks for that.

Print: "⚙️ Phase 2/4 — Cherry-picked <commit> (<N> conflicts resolved)"

If --allow-dirty stashed changes in Phase 0: `git stash pop` now, whether the pick
succeeded or was aborted — the user's WIP must come back either way. If the pop
itself conflicts, surface that explicitly; do not silently drop the stash.

## Phase 3 — Syntax / Build Sanity Check

Same rationale as /jsat-merge's Phase 4: a single commit picked onto a different
base can still compile-fail or fail lint even when git resolved (or found no)
textual conflicts, because the commit's context (other files, dependency versions)
differs from where it originally landed. Run the repo's own lint/typecheck/build
command if one is discoverable (package.json scripts, Makefile, pyproject.toml,
etc.) on the files touched by the pick. This is a mechanical check, not a
substitute for Phase 4's semantic verify.

Print: "🔧 Phase 3/4 — Sanity: <pass/fail>, <N> files checked"

## Phase 4 — Verify + Record

Call: jsat__blast_radius_diff(diff="HEAD~1") — jsat__blast_radius's `target` param
is a file path or symbol name, NOT a git ref, so `target=HEAD` is invalid; use
blast_radius_diff's documented ref-shorthand instead to check the impact of the
commit that just landed. Filter the result to breaking severity yourself (no
`severity_filter` tool parameter exists).
Call: jsat__get_test_gaps(path=<changed paths>) for gaps introduced during resolution.

If the pick had any conflicts to resolve, or Phase 1/4 found breaking impact: call
jsat__knowledge_add(text="CHERRY-PICK: <commit> → <current branch> | Conflicts:
<N files> | Breaking: <yes/no> | Notable resolutions: <one-line per non-trivial
conflict>", category="decision") — same logging discipline as /jsat-merge Phase 6,
so a later merge/rebase touching the same files has this decision to reference.
Skip this call for a clean, conflict-free, non-breaking pick.

Print final summary:
  ✅ Cherry-picked: <commit> onto <current branch>
  📁 Conflicts resolved: <N>
  🔧 Build sanity: <pass/fail>
  💥 Breaking: <N> (pre) → <N> (post)
  📝 Decision logged: <yes/no>
  Rollback (not yet pushed): `git cherry-pick --abort` if mid-pick, else
    `git reset --hard HEAD~1` to drop the pick commit entirely.
  Rollback (already pushed): `git revert <new-commit-sha>` — reset --hard is unsafe
    once others may have pulled the picked commit.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually perform the phases (git via Bash, analysis via jsat__*
tools), then report real outcomes. Never silently resolve a breaking or
deleted-vs-modified conflict — always surface it to the user before continuing.
