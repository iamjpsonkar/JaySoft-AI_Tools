---
description: Check API contract compatibility between branches.
---

Parse $ARGUMENTS, then call jsat__get_api_diff:

Usage:
  (no args)            → jsat__get_api_diff(base="main", head="HEAD")
  <base> <head>        → jsat__get_api_diff(base=<base>, head=<head>)
  --score              → show only the numeric compatibility score (0-100)
  --breaking           → show breaking changes only
  (--score and --breaking together)  → show the score line followed by the
                          breaking-only change list; --score alone never suppresses
                          the change list on its own unless --breaking is absent AND
                          the user asked for the score specifically — if only --score
                          is given, print the score and stop there (that's the
                          documented single-purpose meaning of the flag)

PREFLIGHT — do not trust the "main" default blindly: the tool's own default base is
the literal string "main", which does not exist in every repo (some use `master`,
`trunk`, `develop`, etc.). Before calling with no args, run via Bash:
  `git rev-parse --verify main` (or `git show-ref --verify refs/heads/main`)
If it fails, do NOT call get_api_diff(base="main") — it will silently diff against a
ref that isn't the intended baseline (or error). Instead detect the actual default
branch (`git symbolic-ref refs/remotes/origin/HEAD` → strip `origin/`, or ask the
user) and pass that explicitly as `base`.

This check is about the DEFAULT specifically, but an explicitly-supplied <base> or
<head> is not automatically safe either — a typo'd branch/tag name is just as likely
whether it was typed by the user or substituted by this command. Whenever <base>
and/or <head> come from $ARGUMENTS rather than the default, still run
`git rev-parse --verify <ref>` on each explicit value before calling get_api_diff,
and stop with a clear error naming which one failed to resolve — same discipline
/jsat-merge and /jsat-cherry-pick apply to their own source/target/commit args.

Examples:
  /jsat-contract
    → diff main...HEAD for all OpenAPI/AsyncAPI specs in the repo

  /jsat-contract main feature/new-payments
    → jsat__get_api_diff(base="main", head="feature/new-payments")

Show:
  - Compatibility score (100 = no breaking changes; decays EXPONENTIALLY with the
    number of breaking changes — verified from the tool's own implementation:
    score = round(100 * e^(-0.15 * breaking_count)), so each additional breaking
    change costs progressively less in absolute points but the score never fully
    recovers to 100 once any breaking change exists; do not describe this as
    "logarithmic" or as a flat per-change penalty, both are wrong)
  - Breaking changes: endpoint removed, required field removed, type changed
  - Non-breaking: new endpoints, optional fields added
  - Migration guide: the tool returns this natively as a single pre-formatted
    `migration_guide` string field (one numbered entry per breaking change, already
    tied to the spec file and the exact changed line) — print/relay that field
    verbatim under a "Migration Guide" heading. Do not re-synthesize your own
    migration steps from the raw change list; the field is empty ("") when there are
    no breaking changes, which is the correct, non-error state — show "No migration
    required" in that case instead of an empty section.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
