---
description: Compose a ready-to-post PR description from review findings, contract diff, and test coverage — pure recombination, no new analysis.
---

Parse $ARGUMENTS for optional flags, then positional args: [base] [head].

If [base] is not given, do NOT assume "main" — repos also use master, develop, or a
release branch as their default. Resolve it via Bash: `git symbolic-ref
refs/remotes/origin/HEAD` (strip the `origin/` prefix), falling back to
`git remote show origin | grep "HEAD branch"` if the symbolic-ref isn't set locally.
If [head] is not given, default to the current branch (`git rev-parse --abbrev-ref HEAD`).

Supported flags:
  --no-tests    → skip the test-gaps section (for docs-only / trivial PRs)
  (no flags)    → full PR description: summary, review findings, contract diff, test gaps

Examples:
  /jsat-pr-describe
    → describe the diff between main and the current branch

  /jsat-pr-describe main feature/checkout-retry
    → describe main...feature/checkout-retry

This command does not run any NEW analysis — it recombines results already available
from other /jsat commands into one document. If the user hasn't run a review yet in
this session, run one; don't skip straight to a description built on stale/no data.

## Phase 1 — Gather

Call: jsat__get_review_findings() — an empty result is ambiguous (it could mean "no
review has run this session" OR "a review ran and found nothing"). If the response
includes any indication a review was actually performed (e.g. a run/session marker,
timestamp, or explicit zero-findings status), treat empty as genuinely clean and do
NOT re-run a review. Only call jsat__submit_for_review(diff=<git diff <base>...<head>>)
when there is no such indication — i.e. it looks like no review has run at all —
then re-fetch findings.
Call: jsat__get_api_diff(base=<base>, head=<head>) for contract compatibility.
An empty/no-diff result here is the SAME kind of ambiguous signal as the
review-findings case above: it could mean "no API surface changed" (genuinely
clean) or "the diff tool could not compute a comparison" (e.g. base/head
unresolvable, no OpenAPI/contract spec found, or an internal error swallowed
into an empty result). Before reporting "no breaking changes," sanity-check
that <base> and <head> actually resolved to real refs (`git rev-parse` both)
and that the repo has a contract surface to diff at all — if either check
fails, report "contract diff could not be computed" instead of "no changes."
Unless --no-tests: get the changed paths via `git diff <base>...<head> --name-only`,
then call jsat__get_test_gaps(path=<those changed paths>). Apply the same
ambiguity check: if the changed-paths list is non-empty but get_test_gaps comes
back empty, verify that's "fully covered" and not "tool couldn't analyze these
paths" (e.g. unsupported file types, no test framework detected) before writing
"No new gaps" — if there's no signal either way, say coverage could not be
determined for these paths rather than asserting they're covered.
Call: jsat__blast_radius_diff(diff=<git diff <base>...<head>>, severity_filter=["breaking"])
  to surface anything the PR body must call out explicitly.

Print: "🔍 Phase 1/2 — Gathered: <N> review findings, contract score <X>, <N> test gaps, <N> breaking"

## Phase 2 — Compose

Write the PR description in this structure:

  ## Summary
  <1-3 bullets — what changed and why, derived from the diff and any /jsat decide
  entries relevant to the changed files (call jsat__knowledge_search if useful)>

  ## Breaking changes
  <from blast_radius_diff + get_api_diff — omit this section entirely if none;
  never silently omit a real breaking change to make the PR look cleaner>

  ## Review findings
  <high-confidence findings only from get_review_findings — omit if clean>

  ## Test coverage
  <uncovered paths from get_test_gaps, or "No new gaps" if clean — omit if --no-tests>

  ## Test plan
  <checklist derived from the above: what a reviewer should manually verify>

Print the composed description as the final output — this IS the deliverable,
ready to paste into the PR body. Do not summarize it further; show it in full.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then output the
composed PR description in full — that is the final answer, not a summary of it.
Never fabricate a breaking-change or test-gap number; only report what the tools returned.
