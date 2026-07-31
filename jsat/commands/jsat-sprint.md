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
Create ~/.jsat/sessions/sprint-<SLUG>-<YYYYMMDD-HHMM>.md with all 7 stages as unchecked steps.
Print: "📄 Session: <path>"

### Stage 1 — Think (~10s)
Call: jsat__ithinking_plan(task=<task>)
Extract clarified intent in 1 sentence. Label: "🧠 Stage 1/7 — Think"
Update session file: mark Stage 1 [x] with 1-sentence outcome.

### Stage 2 — Plan (~20s)
Call: jsat__ithinking_audit_assumptions(task=<task>)
Call: jsat__query(question="what already handles: <task>")
Summarize: what exists, what's new, top assumption. Label: "📋 Stage 2/7 — Plan"

### Stage 3 — Build (~15s)
Call: jsat__get_function(name=<key function implied by task>)
Call: jsat__blast_radius(target=<most relevant file or function>)
Show: what to change and what it affects. Label: "🔨 Stage 3/7 — Build"

### Stage 4 — Review (~20s)
Call: jsat__get_review_findings() if a recent review exists
Otherwise: jsat__query(question="code quality or design issues in <relevant area>")
Label: "👁 Stage 4/7 — Review"

### Stage 5 — Test (~20s)
Call: jsat__get_test_gaps(path=<relevant path>)
Show top 3 uncovered paths. Label: "🧪 Stage 5/7 — Test"

### Stage 6 — Ship (~10s)
Call: jsat__blast_radius(target=<changed file or function>)
Filter to breaking impacts only. Flag any before proceeding.
Label: "🚢 Stage 6/7 — Ship"

### Stage 7 — Reflect (~5s)
Call: jsat__ithinking_reflect(subtask="<task> — sprint completed")
Prompt: "Log key decision? Run: /jsat decide log <decision>"
Label: "🔮 Stage 7/7 — Reflect"

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


HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
