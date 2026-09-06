---
description: Plan a refactor so nothing breaks — map the blast radius first, stage the work into behaviour-preserving steps, and only then write code.
---

Parse $ARGUMENTS for the target of the refactor: a symbol, file, or a short description
of what to restructure.

Supported flags:
  --service <name> → scope to one service (avoids timeout on large codebases)
  --dry-run        → produce the plan only; do not edit any file

Examples:
  /jsat-refactor --dry-run payments.py
    → structured, staged refactor plan for payments.py, no edits
  /jsat-refactor "unify the two payment gateway abstractions"
    → plan for the described change, but locate the symbols first

THIS IS NOT A NEW MCP CAPABILITY: it is blast_radius + the call graph turned into a
safe-edit procedure. The refactor planner NEVER edits a file until the blast radius
of that specific file/symbol is counted.

## Phase 1 — Locate and map

If given a description rather than a file, call jsat__query(question="which files and
symbols are involved in <description>?") to locate the surface. Then for EACH
candidate file/symbol call jsat__blast_radius(target=<name>) BEFORE touching anything.
Record for each: breaking / degraded / warning / safe counts and the top downstream
files. Number the refactor surface by blast radius, biggest-first.
Print: "🗺️ Phase 1/4 — surface = <N> files, largest blast radius = <file> (<B> breaking)"
If any file has >0 breaking downstream callers, note that the refactor MUST be staged
so each intermediate commit stays green (see Phase 3).

## Phase 2 — The smallest behaviour-preserving decomposition

Decompose the refactor into the smallest commits that each preserve behaviour:
  - Extract (rename/move a symbol): zero behaviour change by construction
  - Add a parallel implementation behind the existing interface (strangler step)
  - Switch the callers one at a time (each switch = its own commit)
  - Delete the old path only after zero callers remain
For each step, name the exact symbols moved/renamed (from jsat__get_function /
jsat__get_class) and the exact files. Order the steps so that after EVERY step the
codebase still builds and every existing test still passes. If a step cannot be made
behaviour-preserving, mark it ⚠️ and put it LAST, as its own commit, with a rationale.
Print: "🔧 Phase 2/4 — <N> steps, each behaviour-preserving"

## Phase 3 — Guard rails per step

For each step in Phase 2:
  1. jsat__blast_radius(target=<symbol at that step>) → confirm the step touches no
     file outside the planned surface
  2. jsat__get_test_gaps(path=<files the step touches>) → the step's files need a test
     before they are moved or it is untested-code-in-motion
  3. If the step touches a symbol with >0 downstream CALLS edges, that step MUST be a
     separate commit — never bundle a caller-switch with a rename
Produce the commit list: commit message, files, and the verification command for each.
Print: "🛡️ Phase 3/4 — <N> commit(s), <M> with caller-switches (kept separate)"

## Phase 4 — Execution (unless --dry-run)

Execute the commits IN ORDER, verifying after each. Stop and report immediately if any
verification fails — do NOT keep going through a red build, that is how a staged
refactor becomes a mystery regression. Ask before running destructive or wide commands
(external services, migrations).

Print final summary:
  🧹 Refactor complete: <N> commits | before=%R breaking, after=0 breaking
  Top risk that remains: <any behaviour that could not be made identical>

Do NOT use `git push`, do NOT open a PR, and do NOT force-push rewritten history —
this command plans and executes local, verifiable steps; shipping is the human's call.

## Learning from the run

Call jsat__knowledge_add(
  text="REFACTOR <surface>: staged into <N> commits; blast radius dropped from <B> to 0",
  category="refactor")
so the next refactor of the same surface can skip re-discovering the caller map.

BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Run Phase 1 fully (blast_radius on every candidate) before proposing
ANY step — a refactor plan built without the caller map is a guess. In --dry-run mode
do not edit or commit anything; the deliverable is the Phase 2 step list plus the
Phase 3 commit list. When executing, verify after every step and stop on the first red.