---
description: Rebase the current branch onto a target using the same graph-aware, semantic conflict resolution engine as /jsat merge.
---

Parse $ARGUMENTS for optional flags, then positional arg: <onto> (branch/commit to
rebase onto — the current branch is always the one being rebased).

Supported flags:
  --dry-run      → show impact + conflict forecast only, do NOT touch git state
  --continue     → resume a rebase already in progress (conflict markers in the tree)
  --abort        → run `git rebase --abort` and stop (escape hatch, no analysis)
  --no-verify    → skip Phase 3 (test-gaps/breaking check) after the rebase — NOT recommended
  --allow-dirty  → stash uncommitted changes before starting, restore after (Phase 0)
  (no flags)     → rebase current branch onto <onto>, full flow

Examples:
  /jsat-rebase main
    → rebase current branch onto main

  /jsat-rebase --dry-run main
    → show which commits will conflict, without rebasing

  /jsat-rebase --allow-dirty main
    → stash WIP changes first, rebase, then pop the stash back

WARNING — rebase rewrites commit hashes: unlike merge, a rebase you have already
pushed and that anyone else has pulled/branched from CANNOT be safely undone
with a simple reset on their side. Never force-push a rebased branch that others
may have based work on without warning the user first (see Phase 3 rollback note).

This is `/jsat merge`'s conflict-resolution engine applied per-commit instead of
once for the whole branch range. If `/jsat-merge` hasn't been used yet, read its
phases first — Phases 1-4 below are the same semantic approach, just replayed once
per commit being rebased instead of once for the merge.

NOTE ON TOOL USE: git itself has no MCP tool — use Bash for the mechanical
rebase/checkout/diff steps. Use jsat__* MCP tools for all impact/semantic analysis.

## Phase 0 — Preflight

Run via Bash, in order:
  git status --porcelain
    → if dirty: refuse and stop UNLESS --continue, --abort, or --allow-dirty was given.
      With --allow-dirty: `git stash push -u -m "jsat-rebase autostash"` now; remember
      to `git stash pop` in Phase 3 regardless of success or failure.
  git rev-parse --verify <onto>     → confirm the target ref exists; stop with a clear
                                       error if not (rebasing onto a nonexistent ref
                                       fails deep inside git rebase with a much less
                                       useful message — verify up front, same as merge does).
  git rev-parse --abbrev-ref HEAD   → capture the branch being rebased, for the summary
                                       and for rollback guidance.
  git log <onto>..HEAD --oneline    → commits that will be replayed.

Call: jsat__get_index_status() and jsat__list_services() for context.

  git tag --points-at <onto>..HEAD   → tags pointing at any commit in the range
                                       about to be rewritten. Rebase gives every
                                       replayed commit a NEW hash; git does NOT
                                       move tags to follow — any tag found here
                                       will keep pointing at the OLD (now
                                       dangling/orphaned) commit after the rebase
                                       completes, silently diverging from the
                                       branch. If any are found, list them now and
                                       warn the user up front; do not discover
                                       this after the fact. Also check
                                       `git branch --points-at <onto>..HEAD`
                                       (excluding the branch being rebased itself)
                                       for any other branch anchored in the range.

If --abort: `git rebase --abort`, print confirmation, stop. No further phases.
If --continue: skip to Phase 2 using `git diff --name-only --diff-filter=U`.

## No-op short-circuit (check before Phase 1)

Run via Bash: `git merge-base --is-ancestor <onto> HEAD` (exit code 0 means <onto>
is already fully contained in the current branch — there is nothing to replay).
If true: print "⚡ Already up to date with <onto> — nothing to rebase." and stop.
Do not run `git rebase` at all in this case.

## Phase 1 — Blast Radius (before rebasing)

Call: jsat__blast_radius_diff(diff=<git diff <onto>...HEAD>) — same as merge's
Phase 1. Print breaking/degraded/warning/safe counts; require acknowledgment of
any breaking impact before proceeding.

## Phase 2 — Per-commit conflict + resolution

If --dry-run: forecast ONLY, never start a real rebase — starting-then-aborting
a rebase to "see" conflicts is exactly the destructive trial-merge anti-pattern
/jsat-merge's fix removed, and it leaves the tree mid-rebase if anything
interrupts the flow before the abort runs. Instead, for each commit in the
Phase 0 commit list (oldest first), run non-mutating forecasts only:
  `git merge-tree $(git merge-base <onto> <commit>) <onto> <commit>`
  (approximates what that commit would conflict with when replayed onto <onto>;
  note in the output that this is an approximation — true per-commit rebase
  conflicts can differ slightly once earlier commits have already been replayed).
Print the forecasted conflicts per commit and STOP. Do not touch git state.

If NOT --dry-run:
Run via Bash: `git rebase <onto>` (or resume via `git rebase --continue` in a loop
after each conflict is resolved, if --continue).

For EACH commit that stops with conflicts:
  1. Read both sides (`git show :2:<file>`, `git show :3:<file>`, `git show :1:<file>`).
  2. Determine intent per side using jsat__query/jsat__get_function against the graph
     — same semantic approach as /jsat-merge Phase 3.
  3. Resolve, stage (`git add <file>`), `git rebase --continue`.
  4. Never silently resolve a deleted-vs-modified conflict — surface it.
  5. If `git rebase --continue` fails because a pre-commit/commit-msg hook
     rejected the replayed commit: report the hook's exact output, fix what it
     flagged (or ask the user how to proceed), re-stage, and retry `git rebase
     --continue` — do not bypass with git's own `--no-verify` unless the user
     explicitly asks for that (distinct from this command's --no-verify flag,
     which only skips Phase 3).

Print progress per commit: "⚙️ Phase 2/3 — Replayed <short-hash> (<N> conflicts resolved)"

## Phase 3 — Verify (skipped if --no-verify)

Call: jsat__blast_radius(target=HEAD, severity_filter=["breaking"]) — post-rebase check.
Call: jsat__get_test_gaps(path=<changed paths>) for any gap introduced during resolution.

If --allow-dirty stashed changes in Phase 0: `git stash pop` now, whether the
rebase succeeded or was aborted — the user's WIP must come back either way. If
the pop itself conflicts, surface that explicitly; do not silently drop the stash.

Print final summary:
  ✅ Rebased onto: <onto>
  📁 Commits replayed: <N>, conflicts in <N>
  💥 Breaking: <N> (pre) → <N> (post)
  Rollback (not yet pushed): `git rebase --abort` if still mid-rebase, or
    `git reset --hard ORIG_HEAD` if the rebase already completed but you have
    not pushed <original-branch> anywhere yet.
  Rollback (already pushed / shared): DO NOT `git push --force` without warning —
    rebase changes every replayed commit's hash, so anyone who already pulled
    the old branch will get diverged history. If a force-push is truly required,
    use `git push --force-with-lease` (never plain --force) and explicitly tell
    the user to notify collaborators before doing so.
  Orphaned refs: if Phase 0 found tags or other branches pointing into the
    rewritten range, they now point at commits that are no longer reachable from
    <original-branch> (dangling until gc, and diverged from the new history even
    if kept). Re-tag/re-point them at the corresponding new commit explicitly
    (e.g. `git tag -f <tag> <new-hash>`) — this does NOT happen automatically as
    part of the rebase, and forgetting it means the tag silently stops matching
    what people think it points to.


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
Never leave the tree in a half-rebased or half-stashed state — every mutating
step in Phase 0 has a matching cleanup in Phase 3 regardless of whether the
rebase itself succeeds.
