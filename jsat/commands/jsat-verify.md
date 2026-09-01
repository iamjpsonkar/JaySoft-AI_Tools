---
description: Prove a code change actually works by driving it end-to-end, prioritized by graph impact rather than blind manual testing.
---

Parse $ARGUMENTS for optional flags, then positional arg: <target> (file, symbol, or
free-text description of what changed — defaults to the current uncommitted diff).

Supported flags:
  --service <name>   → scope graph lookups to one service (avoids timeout on large repos)
  --claim <text>     → the specific behavior to verify ("returns 402 on insufficient funds")
                        instead of verifying everything blast-radius surfaces
  (no flags)         → verify the current diff's most-impacted paths

Examples:
  /jsat-verify src/payment/service.py
    → blast-radius + test-gaps on that file, then drive the affected behavior live

  /jsat-verify --claim "refund retries 3x on timeout" src/payment/retry.py
    → verify one specific claim instead of the whole diff

DIFFERENCE FROM THE GENERIC `verify` SKILL: that skill drives the app blind — it has
no way to know which behaviors a change actually touches. This command uses the
graph to prioritize *what* to exercise before touching the app, so verification time
goes to the highest-risk paths first instead of guessing.

NOTE ON TOOL USE: there is no `jsat__run_app` MCP tool — launching and driving an
app is inherently repo-specific (dev server command, ports, fixtures). Use the
project's own `run`/`verify` Claude Code skill or Bash to do the actual driving.
Use `jsat__*` MCP tools for everything analytical: what to check, and what to log.

## Phase 1 — Scope the change

If <target> is a file/symbol: call jsat__blast_radius(target=<target>) (or
jsat__blast_radius_diff(diff=<git diff>) if no target was given — verify the
current uncommitted change). Extract the list of behaviors/callers actually
affected — this is what needs live verification, not the whole file.

Call: jsat__get_test_gaps(path=<target or changed paths>) to see which of those
affected behaviors already have automated coverage (lower priority to hand-verify)
vs none (highest priority — this is the actual risk).

Print: "🔍 Phase 1/4 — Scope: <N> affected behaviors, <M> untested, <K> breaking-impact"

## Phase 2 — Drive it for real

For each untested / breaking-impact behavior from Phase 1 (or the single --claim
if one was given): actually exercise it — run the affected code path, hit the
affected endpoint, or drive the affected UI flow. Use whatever mechanism the repo
already provides (dev server, test fixture, curl, browser automation). Determine
HOW to launch/drive the app by checking, in this order, before improvising a
command from scratch:
  1. An existing `run` or `verify` Claude Code skill/script already in this repo.
  2. Project-native run commands: package.json `scripts` (`dev`/`start`/`serve`),
     a Makefile target, `pyproject.toml`/`tox.ini` entries, `manage.py runserver`,
     or similar framework convention for this repo's language.
  3. CI/deploy config as a source of truth for the real launch command: GitHub
     Actions / GitLab CI workflow files, a `Dockerfile`/`docker-compose.yml`
     CMD/entrypoint, or a `Procfile` — these encode how the app is actually run
     in an environment that isn't a developer's own head, which is exactly the
     failure mode "guessing a launch command from scratch" produces.
  4. Only if none of the above exist: construct a minimal launch command
     yourself, state explicitly that you improvised it (so the user can correct
     it if it's wrong), and prefer the narrowest scope that exercises just the
     affected behavior (a single test fixture or curl call) over booting the
     whole app if that's sufficient to observe the behavior.

CONTRADICTIONS BETWEEN SOURCES: this precedence list assumes the sources agree.
They frequently don't — e.g. package.json's "start" script runs a dev server
with hot-reload/mocked auth, while the Dockerfile's CMD runs a production
entrypoint with different env vars, migrations-on-boot, or a different port.
Picking whichever source ranks higher in the list without checking for
disagreement can mean "verifying" a code path the real deployment never
executes. When more than one source exists, do not just take the first match
found in precedence order — check whether they actually agree on the command,
entrypoint, and relevant env/config. If they disagree:
  - Prefer whichever source reflects the environment the behavior being
    verified actually depends on. If the change or --claim concerns something
    env/runtime-sensitive (prod-only feature flags, migrations run on boot,
    a middleware only active outside DEBUG mode), the CI/Dockerfile source is
    almost always the one that matches — dev scripts commonly short-circuit
    exactly those paths. If the change is pure application logic with no
    env-dependent branching, the faster dev-script path is a legitimate and
    more practical choice.
  - Either way, state the contradiction explicitly to the user (which two
    sources disagreed and how) rather than silently picking one — do not
    present the result as "verified" without disclosing that verification
    used one of two disagreeing launch paths, since a pass under the dev
    script does not prove the same behavior holds under the prod entrypoint.

Observe real output/behavior, not just "it compiled" or "the test passed" — the
whole point is proving the RUNTIME behavior matches intent.

Print progress per behavior: "▶ Phase 2/4 — Verifying: <behavior> ... <pass/fail>"

## Phase 3 — Cross-check against static analysis

Re-run whichever call Phase 1 actually used: jsat__blast_radius(target=<target>,
severity_filter=["breaking"]) if a <target> was given, or
jsat__blast_radius_diff(diff=<same diff used in Phase 1>, severity_filter=["breaking"])
if Phase 1 fell back to the diff (no <target> given) — do not switch to the
target-based call here if Phase 1 never had a target to begin with, since a
diff-scoped verification has no single symbol to re-query.
If a breaking impact from Phase 1 was NOT actually observed as broken in Phase 2,
flag the discrepancy explicitly (either the static analysis over-flagged it, or
the live verification missed it — never silently resolve which).

Print: "🔧 Phase 3/4 — Cross-check: <N> confirmed, <N> discrepancies flagged"

## Phase 4 — Record

If a real bug was found during verification (not just a gap in test coverage):
  Call: jsat__knowledge_add(text="VERIFY: <target> — found <bug description> during
  live verification, not caught by static analysis", category="decision")

If verification passed clean: no knowledge entry needed — this was routine.

Print final summary:
  ✅ Verified: <N>/<M> affected behaviors, live-tested
  ⚠️  Untested-but-verified-manually: <N> (candidates for /jsat test-gaps --generate)
  🐛 Bugs found: <N> (<one-line each>)
  📝 Logged: <yes/no>


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually drive the app/tests as described above (graph analysis via
jsat__* tools, execution via Bash/existing skills), then report real observed
behavior — never claim something is "verified" without actually having run it.
