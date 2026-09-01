---
description: Workflow advisor — classifies your task and runs the optimal JSAT tool sequence end-to-end.
---

Given a task in $ARGUMENTS, act as a JSAT workflow advisor.
Classify the task, announce the recommended tool sequence, then run each step.

## Step 1 — Classify task type

Read the task description and identify the type:

  feature    → adding new functionality to the codebase
  bugfix     → fixing broken or incorrect behavior
  security   → security audit, hardening, or vulnerability check
  understand → exploring or learning how existing code works
  incident   → investigating a production issue or alert
  refactor   → improving existing code without changing behavior
  review     → reviewing a diff or PR before merge

If the task description matches more than one type (e.g. "fix this SQL injection bug"
is both bugfix and security, or a task is explicitly ~50/50 between two types), do
NOT force a single bucket and do NOT silently pick whichever type happened to be
checked first. Instead:
  - Pick the type whose workflow starts with the more information-gathering-heavy
    step for THIS task (security > bugfix > refactor > feature > understand, in that
    priority order, when two types tie) as the primary type, and note the secondary
    type explicitly in the announcement: "📋 Task type: bugfix (security overlap)".
  - After the primary workflow's first 1-2 steps produce results, apply the ADAPT
    rule in Step 3.5 below to fold in the secondary type's distinguishing step
    (e.g. jsat-security) if the findings so far confirm the overlap is real.
Only default to "understand" when NO type keyword/intent matches at all — defaulting
to "understand" for a genuinely ambiguous but clearly-actionable task (e.g. "clean up
the payment retry logic" — actually a refactor) silently produces the wrong, much
lighter-weight workflow. Prefer asking the user to disambiguate over guessing wrong
when the task is a plausible fit for 2+ non-"understand" types.

## Step 2 — Announce the workflow

Show the recommended sequence before running anything:

  feature:   jsat-lazy → jsat-find-function → jsat-blast-radius → jsat-crack → jsat-test-gaps
  bugfix:    jsat-recent → jsat-incident → jsat-find-function → jsat-blast-radius
  security:  jsat-security → jsat-blast-radius --severity breaking → jsat-crack --phases 3 → jsat-knowledge add
  understand:jsat-smart → jsat-trace → jsat-find-function → jsat-query
  incident:  jsat-incident → jsat-recent → jsat-blast-radius → jsat-runbook
  refactor:  jsat-lazy → jsat-blast-radius → jsat-test-gaps → jsat-crack → jsat-review
  review:    jsat-review → jsat-blast-radius --severity breaking → jsat-test-gaps --untested

Print before running:
  "📋 Task type: <type>"
  "🔄 Workflow (<N> steps): step1 → step2 → ..."

## Step 3 — Execute each step in sequence

Each workflow step name (e.g. "jsat-lazy", "jsat-crack") is a /jsat sub-command, NOT
a 1:1 MCP tool name — several of them (jsat-lazy, jsat-smart, jsat-decide) run a
multi-phase procedure across several jsat__* tools, not a single same-named call.
Do not literally call a tool named e.g. `jsat__lazy` (it does not exist). Instead,
run that step by following the logic documented in its own command file
(jsat/commands/<skill-name>.md) — same MCP tools, same order, same fallbacks — using
the task description (or the most relevant part) as its argument, plus any flags
shown in the workflow.

For each step:
  1. Execute the sub-command's documented logic as described above.
  2. Show the result under the header "✅ Step N/M — <skill-name>".
  3. Before extracting a finding, check the raw result for degraded/failed output —
     an "[AI unavailable" prefix (jsat__query-backed steps, e.g. jsat-smart or a bare
     jsat__query call, fail this way whenever the AI backend is down or unconfigured —
     this is common, not rare) or an empty/error result. If degraded:
       - Print "⚠️ Step N/M — <skill-name>: degraded result (AI backend unavailable) —
         not carrying this forward as a finding."
       - Do NOT extract a "key finding" from it, and do NOT feed it as context into
         later steps — a bad finding here would silently corrupt every step after it.
       - If the step has an AI-free alternative already documented in its own file
         (e.g. jsat-smart has none; prefer jsat__blast_radius / jsat__list_services /
         jsat__get_function / jsat__list_endpoints directly for that step's intent
         instead), use it and note the substitution in the summary.
  4. Otherwise, extract the key finding in 1 sentence and carry it forward as
     additional context to the next step where useful.
  5. Before each step, print: "▶ Step N/M — <skill-name>: <what it checks>"

COMPOUNDING BUDGET: each step carries its own soft timeout (see BUDGET below); a
full 4-5 step workflow can therefore take several times a single tool's budget to
finish. For a large or unfamiliar repo, run with --dry first to see the planned
sequence, and consider passing timeout=<N> to individual steps that are known to be
slow (e.g. blast-radius on a wide diff) rather than letting every step use the
default budget.

## Step 3.5 — Adapt the sequence (do not run it on rails)

The per-type sequences in Step 2 are a starting plan, not a contract — unlike a
single fixed pipeline, this command runs several steps back-to-back specifically so
that early results can change what runs later. After each non-degraded step, check
whether its finding contradicts or extends the original classification, and adjust
the REMAINING steps before running them:
  - A bugfix/refactor/feature step surfaces something that looks like a real
    vulnerability (injection, auth bypass, secret exposure) → insert
    jsat-security (or jsat__security_review directly) before the next step, even
    though the "bugfix"/"refactor"/"feature" sequence never listed it.
  - An "understand" or "incident" step reveals the task is actually going to require
    a code change (not just investigation) → insert jsat-blast-radius and
    jsat-test-gaps before the final summary if they are not already later in the
    sequence, since a change is now in scope.
  - A step's finding makes a LATER planned step redundant (e.g. jsat-recent already
    surfaced the exact commit that caused the incident, making a broad jsat-incident
    pass unnecessary) → skip that step and say so explicitly rather than running it
    for form's sake: "⏭ Skipping step <N> (<skill-name>): superseded by step <M>'s finding."
Print any adaptation as: "🔀 Adapting workflow: inserting/skipping <skill-name> — <one-line reason>"
before the next "▶ Step" line, so the printed sequence from Step 2 and the sequence
actually executed can visibly diverge and the user can see why.

## Step 4 — Final summary

After all steps complete, produce:

  📊 **Workflow Summary**
  - Task: <original task>
  - Type: <classified type>
  - Steps run: <N>
  - Key findings: <one bullet per step>
  - Recommended action: <1-2 concrete next steps>
  - Save to knowledge base: <yes/no — if yes, use jsat-knowledge add>

## Flags

  --type <type>   → skip classification, force a specific workflow type
  --dry           → show the workflow plan only, do NOT run any tools
  (no flag)       → classify + run full workflow

Examples:
  /jsat-aw add idempotency keys to the payment mutation endpoint
    → classifies as "feature": lazy → find-function → blast-radius → crack → test-gaps

  /jsat-aw --type security src/auth/
    → skips classification, runs security workflow on src/auth/

  /jsat-aw --dry investigate the checkout 500 errors from this morning
    → prints the "incident" workflow plan without executing anything


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
