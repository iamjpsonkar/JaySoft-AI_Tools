---
description: Plan and verify a release of this repository — diff the contract, check the blast radius, confirm nothing untested ships, and produce the release notes.
---

Parse $ARGUMENTS for optional flags, then positional arg: [from-ref] (defaults to the last tag / `main`).

Supported flags:
  --to <ref>      → target ref to release (default: HEAD)
  --service <name>→ scope the analysis to one service

Examples:
  /jsat-release
    → plan a release of HEAD against the last tag
  /jsat-release v0.3.0 --to HEAD
    → release v0.4.0 (or whatever you are shipping) against v0.3.0

THIS IS NOT A NEW MCP CAPABILITY: it sequences existing tools (api_diff, blast_radius,
test_gaps, review) into a release-verification pipeline.

## Phase 1 — What changed

Call: jsat__get_api_diff(base=<from-ref>, head=<to>) to learn which public contracts
changed (OpenAPI / AsyncAPI). Then jsat__get_recent_changes(since=<from-ref>) for the
commit list. Compute the semantic version bump from the api_diff result:
  breaking changes → MAJOR bump
  new contract surface (additive) → MINOR
  fixes only → PATCH
Print: "📦 Phase 1/4 — <N> commits, <M> contract changes → suggests <major|minor|patch>"

## Phase 2 — Who breaks

For every breaking change found in Phase 1, call jsat__get_consumers(target=<changed symbol or endpoint>)
and jsat__blast_radius(target=<the contract file>) to enumerate downstream callers.
Group consumers into:
  🔴 breaking  — inbound callers that will fail to compile/validate after the change
  🟡 degraded  — consumers whose behaviour silently changes (defaults, error codes, timing)
List the top items with file:line and a one-line migration each. This section answers
"who outside this codebase (or this service) must know before this ships."
Print: "💥 Phase 2/4 — <N> breaking consumers, <M> degraded"

## Phase 3 — Test gaps on the changed surface

Call: jsat__get_test_gaps(path=<paths touched since from-ref>) — for the files touched
by the release. Report the count of changed-but-untested functions. Do NOT block the
release on new tests you could write later; instead flag the ones that gate a
rollback: anything that a consumer breaking change touches should at minimum have a
contract test, or the release is not safe to ship without a coordination note.
Also call jsat__submit_for_review(base=<from-ref>, head=<to>) if review findings are
cheap to fetch, and surface only medium+ confidence findings that intersect the
changed surface.
Print: "🧪 Phase 3/4 — <N> untested changed paths; review found <M> medium+ findings on the changed surface"

## Phase 4 — Release plan

Produce, in order:
  1. Version suggestion (from Phase 1) and a proposed tag name
  2. The migration notes consumer teams need (from Phase 2), each with the owning file
  3. The rollback plan — which commit to revert if the release goes sideways, and what
     state the DB/product will be in between (use jsat__blast_radius on the primary
     changed module if unsure what a revert touches)
  4. The release notes draft (from Phase 1 commit list), grouped Breaking / Added /
     Fixed — HTML/markdown-safe, no internal paths, no raw tracebacks
  5. A checklist: contract diff reviewed / consumers notified / gaps accepted /
     rollback commit identified

Print final summary:
  📦 Release <tag>: <bump> bump · <N> consumers to notify · rollback = <commit>
  The single most important pre-ship check: <the top breaking consumer>

Do NOT push the tag, open the release PR, or publish — this command plans and
verifies; the human ships.

## Learning from the run (do this every run)

Call jsat__knowledge_add(
  text="RELEASE <tag>: api_diff=<n> breaking, consumers=<N>, gapped tests=<N>, rollback=<commit>",
  category="release")
so the next release can compare trajectory and spot a pattern (e.g. "third release
in a row bumping the same contract — needs a deprecation notice").

BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the jsat__* tools described above in order, then
reply with the Phase 4 release plan. If jsat__get_api_diff or jsat__get_recent_changes
needs a graph the repo hasn't indexed, say so and ask the user to run `jsat index .`
rather than guessing at the diff from git alone — the contract diff is the load-bearing
input here. Never ship a tag or push anything without explicit human confirmation.