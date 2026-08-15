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

Step 2 — unless --list was passed, run the analysis in the terminal:
  The diagnosis itself is a CLI command, not an MCP tool, because it calls the
  user's AI provider and writes a bundle to disk:

    jsat improve                 (or: jsat improve --id <fp8>)

  Report back: the issue chosen, the patch status (validated / did_not_apply /
  no_patch / no_ai), and the bundle path.

Step 3 — if --report was passed, tell the user to run:
    jsat improve --report

  This opens a pre-filled GitHub issue. Emphasise that NOTHING is transmitted until
  they read it and press Submit themselves.

PRIVACY — state this plainly whenever the user asks what is collected:
  Only JSAT-internal data is ever recorded: JSAT's own stack frames, exception type
  names, tool names, versions, and config KEYS. Code, file paths, identifiers, and
  queries from the user's own project are dropped, never redacted. Capture is a
  local file (~/.jsat/improve/); nothing leaves the machine without --report.
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
