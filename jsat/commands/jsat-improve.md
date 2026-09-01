---
description: Diagnose problems JSAT hit in itself and draft a patch to JSAT's own source.
---

Parse $ARGUMENTS for optional flags:

  --list          → only show what has been recorded, analyse nothing
  --id <fp8>      → work on one specific recorded issue
  --report        → open a pre-filled GitHub issue in the browser after diagnosing
  (no flag)       → diagnose the most frequent unreported issue

JSAT passively records friction it encounters in ITSELF — crashes, capability gaps,
bad error messages, and tools that blow their time budget. This command turns those
recordings into a concrete fix proposal.

Step 1 — see what is recorded:
  Call: jsat__improve_status()

  This returns the issue clusters with counts. It is read-only and costs no tokens.
  If it returns no clusters, tell the user there is nothing to improve and stop.

  "Diagnose the most frequent unreported issue" (the no-flag default) needs a
  tie-break rule when two or more clusters share the top count — "most frequent"
  alone is ambiguous the moment there's a tie, and picking arbitrarily means two
  runs back-to-back could diagnose different issues nondeterministically with no
  explanation to the user. Break ties in this order: (1) prefer the cluster whose
  most recent occurrence timestamp is more recent — a tied-frequency issue that's
  actively recurring right now is more actionable than one that hasn't fired
  since; (2) if still tied, prefer the cluster already carrying a fp8 ID from a
  PRIOR unresolved bundle (see loop-detection below) over a fresh one, so recurring
  work converges instead of round-robining between equally-frequent issues forever;
  (3) if still tied, prefer lexicographically-lowest fp8 ID purely for determinism,
  and say so ("tie broken by ID for determinism") rather than presenting the choice
  as if frequency alone decided it.

  LOOP DETECTION — before running Step 2, check whether the chosen cluster's fp8 ID
  already has an existing bundle under ~/.jsat/improve/bundles/ from a previous run
  (list that directory or check for a file named after the fp8). If it does, this is
  a REPEAT diagnosis of an issue nobody has fixed yet:
    - Do not silently regenerate an identical bundle and present it as new progress.
    - Tell the user explicitly: "This is the Nth time <fp8> has been the top
      unreported issue (last diagnosed <date/bundle path>) — it's still recurring,
      which means the prior patch was never applied/merged, or didn't fix the root
      cause." Count N by counting prior bundles for that fp8 if the directory makes
      that determinable, otherwise say "at least once before" rather than fabricating
      a precise count.
    - Still produce a fresh diagnosis (the underlying code may have changed since
      the last bundle), but frame it as an escalation, not a first discovery — a
      /jsat improve that quietly re-diagnoses the same unfixed issue on every run
      forever, with each run looking like fresh news, trains users to ignore it.

Step 2 — unless --list was passed, run the analysis in the terminal:
  The diagnosis itself is a CLI command, not an MCP tool, because it calls the
  user's AI provider and writes a bundle to disk:

    jsat improve                 (or: jsat improve --id <fp8>)

  Report back: the issue chosen, the patch status (validated / did_not_apply /
  no_patch / no_ai), and the bundle path.

Step 3 — if --report was passed, before telling the user anything is safe to
submit, VERIFY the privacy claim rather than asserting it on faith: Read the
bundle's issue.md (path reported in Step 2) yourself and scan it for anything
that looks like the user's own file paths, identifiers, code snippets, or query
text — the privacy filter is a piece of software and can have bugs like any
other. If you spot anything that looks like project-specific data rather than
JSAT-internal stack frames/exception names/tool names/versions/config keys, STOP
and tell the user explicitly what you found before they run --report — do not
tell them it's safe to submit an unverified bundle.

  Only after that check passes, tell the user to run:
    jsat improve --report

  This opens a pre-filled GitHub issue. Emphasise that NOTHING is transmitted until
  they read it and press Submit themselves — your check is a second opinion, not a
  replacement for their own read of the pre-filled issue body.

Error handling: if --id <fp8> was given and jsat__improve_status()'s clusters do
not contain that ID, say so and show the valid IDs from the clusters that were
returned — do not pass an unresolved --id straight through to the `jsat improve`
CLI call and let it fail with a raw error.

PRIVACY — state this plainly whenever the user asks what is collected, but do not
present it as a verified fact unless you have actually done the Step 3 check above
for the bundle in question:
  Only JSAT-internal data is intended to be recorded: JSAT's own stack frames,
  exception type names, tool names, versions, and config KEYS. Code, file paths,
  identifiers, and queries from the user's own project are meant to be dropped,
  never redacted — but this is a claim about the filter's design intent, not a
  guarantee for every bundle; verify the actual bundle content (Step 3) before
  repeating this claim as settled fact about a specific run. Capture is a local
  file (~/.jsat/improve/); nothing leaves the machine without --report.
  Disable with JSAT_NO_IMPROVE=1, privacy.no_telemetry, or improve.enabled: false.
  JSAT never modifies its own installed files — a patch stays inert data until a
  human reviews it in a pull request.

## Universal flag carry-through

If ARGS contain timeout=<N> or dashboard=true, strip them and pass as
_budget=<N> / _dashboard=True / _dashboard_session="improve" to every jsat__ call.

HOW TO RESPOND:
Lead with the issue and how often it happened. Then the root cause in one or two
sentences, then the patch status and bundle path. Do not paste the whole diff unless
asked — point at the bundle instead.
