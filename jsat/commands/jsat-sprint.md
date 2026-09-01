---
description: Seven-stage delivery workflow — Think → Plan → Build → Review → Test → Ship → Reflect, each stage fast and focused.
---

Seven-stage sprint workflow for structured project delivery. Each stage runs focused JSAT tools and passes findings forward.

Parse $ARGUMENTS:
  --stage <1-7>    → resume from a specific stage (skip earlier stages)
  --dry            → show the sprint plan without running any tools
  --continue       → resume most recent in_progress sprint session
  (no flag)        → run all 7 stages sequentially

## --continue Flag

When --continue is given:
  1. List ~/.jsat/sessions/sprint-*.md; find most recent with status: in_progress
  2. Read it; find first "- [ ]" stage; carry ## Findings as context
  3. Print: "▶ Resuming sprint: <filename>"
  4. Resume from that stage

If no sprint-*.md file has status: in_progress (all completed, or none exist):
stop and say so explicitly — do not silently start a brand-new sprint under
--continue, since that would run without the task the user originally gave
and confuse "resuming" with "starting fresh".

## --stage <N> Flag

--stage <N> skips stages 1..N-1 entirely, but stages 2-7 all reference outputs
from earlier stages (<task>'s clarified intent, the "what exists" summary, the
file/function actually being changed, etc.) — jumping in cold has nothing to
substitute those with. Before running the requested stage:
  1. Require an existing session file for this sprint (via --continue-style
     lookup, or an explicit session path argument) — --stage without a session
     to pull prior-stage context from is not a valid combination; refuse and
     say so rather than guessing placeholder values for <task>/<relevant path>.
  2. Verify stages 1..N-1 are ALL marked [x] (completed) in that session file —
     an existing session file is not sufficient on its own. A stage can be
     present but not [x]: marked "⚠ blocked: AI unavailable" (per the
     AI-DEPENDENCY WARNING below) or simply never reached before the run
     stopped. Jumping to --stage N when an earlier stage is blocked/incomplete
     silently proceeds on missing or placeholder context — the same failure
     mode as skipping it outright. If any of stages 1..N-1 is not [x]:
     refuse and tell the user to run --continue instead (which resumes from
     the first incomplete stage) rather than --stage N.
  3. Specifically for Stage 6 (Ship): if Stage 6 is among the skipped prior
     stages and its recorded ## Findings show breaking impacts that were
     flagged but never explicitly acknowledged by the user (see Stage 6
     below), --stage 7 must NOT proceed straight to Reflect and mark the
     sprint ship-ready — that gate exists specifically to stop this. Refuse
     and surface the unacknowledged breaking impacts first.
  4. Load the ## Findings recorded by every stage before N from that session
     file and use them verbatim as the context those stages would otherwise
     have produced.

Stage map:
  1. Think   — clarify intent and surface assumptions
  2. Plan    — forcing questions + scope/architecture/security review
  3. Build   — find what exists, map impact scope
  4. Review  — multi-model code review of affected areas
  5. Test    — find test gaps, generate missing cases
  6. Ship    — breaking blast-radius check before release
  7. Reflect — log decisions and outcomes

## Stage execution

### Session File (before Stage 1)
Create ~/.jsat/sessions/sprint-<SLUG>-<YYYYMMDD-HHMM>.md with all 7 stages as
unchecked steps AND an empty "## Findings" section beneath them (--continue and
--stage both read ## Findings for prior-stage context, so it must exist from
the start, not be added ad hoc later). Every stage below writes into this
section, not just Stage 1.
Print: "📄 Session: <path>"

AI-DEPENDENCY WARNING (applies to every stage below): Stages 1, 2 (query call),
4 (fallback query call), and 7 call jsat__ithinking_plan / jsat__query /
jsat__ithinking_audit_assumptions / jsat__ithinking_reflect, all of which need a
working LLM backend and can return "[AI unavailable: ..." when the provider is
down — a common failure mode, not a rare one. If any stage's call returns that,
do NOT record the error text as the stage's finding and mark it [x] as if it
succeeded — that corrupts every later stage's context and --continue's resume
point. Instead: mark the stage's checklist item with a "⚠ blocked: AI
unavailable" note (not [x]), stop the sprint there, and tell the user to fix
the AI provider (e.g. `jsat doctor`) and resume with --continue once it's back.
Stages 3, 5, and 6 use only jsat__get_function/jsat__blast_radius/
jsat__get_test_gaps, which are pure graph lookups with no LLM dependency, so
they can proceed even while AI is down — running them out of order to make
partial progress is fine, but Stage 7's Reflect still needs AI and should stay
blocked until it's back.

### Stage 1 — Think (~10s)
Call: jsat__ithinking_plan(task=<task>)
Extract clarified intent in 1 sentence. Label: "🧠 Stage 1/7 — Think"
Update session file: mark Stage 1 [x] with 1-sentence outcome, and append it to
## Findings as "Stage 1 (Think): <outcome>".

### Stage 2 — Plan (~20s)
Call: jsat__ithinking_audit_assumptions(task=<task>)
Call: jsat__query(question="what already handles: <task>")
Summarize: what exists, what's new, top assumption. Label: "📋 Stage 2/7 — Plan"
Update session file: mark Stage 2 [x], append "Stage 2 (Plan): <summary>" to
## Findings — Stage 3 onward needs "what's new" to know what to build.

### Stage 3 — Build (~15s)
Call: jsat__get_function(name=<key function implied by task>)
Call: jsat__blast_radius(target=<most relevant file or function>)
Show: what to change and what it affects. Label: "🔨 Stage 3/7 — Build"
Update session file: mark Stage 3 [x], append the target file/function and
blast-radius severity counts to ## Findings — Stages 5/6 scope their path/target
args from this.

### Stage 4 — Review (~20s)
Call: jsat__get_review_findings() if a recent review exists
Otherwise: jsat__query(question="code quality or design issues in <relevant area>")
Label: "👁 Stage 4/7 — Review"
Update session file: mark Stage 4 [x], append findings summary to ## Findings.

### Stage 5 — Test (~20s)
Call: jsat__get_test_gaps(path=<relevant path>)
Show top 3 uncovered paths. Label: "🧪 Stage 5/7 — Test"
Update session file: mark Stage 5 [x], append top gaps to ## Findings.

### Stage 6 — Ship (~10s)
Call: jsat__blast_radius(target=<changed file or function>)
Filter to breaking impacts only. Flag any before proceeding — do not let Stage
7 run (and mark the sprint "ship ready") if breaking impacts were found here
and not explicitly acknowledged by the user.
Label: "🚢 Stage 6/7 — Ship"
Update session file: mark Stage 6 [x], append breaking-impact count to ## Findings.

### Stage 7 — Reflect (~5s)
Call: jsat__ithinking_reflect(subtask="<task> — sprint completed")
Prompt: "Log key decision? Run: /jsat decide log <decision>"
Label: "🔮 Stage 7/7 — Reflect"
Update session file: mark Stage 7 [x], append outcome to ## Findings.

### Final Summary
  ✅ Stages completed: N/7
  🚢 Ship readiness: yes/no (Stage 6 broke nothing → yes)
  📝 Decisions to log: <architectural choices made during sprint>

Update session file: status → completed.
Print: "✅ Session complete: <path>"
(If interrupted, run /jsat sprint --continue to resume from the last incomplete stage.)

## Actions File

From sprint outcomes, extract concrete remaining work:
  - Decisions to log (from Stage 7 Reflect)
  - Test gaps to fill (from Stage 5 Test)
  - Breaking changes to fix before shipping (from Stage 6 Ship)
  - Any code changes identified but not yet implemented

Write ~/.jsat/sessions/sprint-actions-<SLUG>-<YYYYMMDD-HHMM>.md.
Print: "📋 Actions: <path>"

Execute each "- [ ]" action in sequence. Mark [x] as done.
When all done: status → completed. Print: "✅ All actions complete: <path>"



BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
