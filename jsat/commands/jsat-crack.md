---
description: Multi-agent war room with artifact carry-forward — each agent builds on prior findings.
---

Parse $ARGUMENTS for optional flags:

  --phases N   → run in N phases (2-6, default: 6)
  --single     → run all agents at once (original one-shot behavior, may timeout)
  --continue   → resume the most recent in_progress crack session
  (no flag)    → 6-phase mode with artifact carry-forward (recommended)

## --continue Flag

When --continue is given:
  1. List ~/.jsat/sessions/crack-*.md; find the most recent with status: in_progress
  2. Read it; extract task and findings from ## Findings as accumulated HANDOFF context
  3. Find first "- [ ]" phase — resume execution from that phase
  4. Print: "▶ Resuming crack session: <filename>"

## Phased Mode (default)

Runs 6 agents sequentially. Each agent receives the original task PLUS a running
brief of all prior agents' key findings — agents build on each other's work
rather than operating in isolation. The skeptic specifically challenges the
architect's and implementer's proposals.

Phase splits (strip --phases flag; task = everything else):
  N=2: [architect,security,implementer] / [tester,skeptic,moderator]
  N=3: [architect,security] / [implementer,tester] / [skeptic,moderator]
  N=4: [architect] / [security,implementer] / [tester,skeptic] / [moderator]
  N=5: [architect] / [security] / [implementer] / [tester,skeptic] / [moderator]
  N=6 (default): one agent per phase — maximum granularity

## Phase 0 — Codebase Context (run before Phase 1)

Call: jsat__get_index_status()
Call: jsat__list_services()
Build CONTEXT_BRIEF from the results: node count, edge count, top service names.
Prepend CONTEXT_BRIEF to every agent's task for grounding.

Create session file: ~/.jsat/sessions/crack-<SLUG>-<YYYYMMDD-HHMM>.md
Content: all 6 phases as unchecked steps in ## Steps, ## Findings empty.
Print: "📄 Session: <path>"

## War Room Phases

### Phase 1 — Architect
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

Structure your response:
**Findings**: what exists in the codebase relevant to this task
**Concerns**: top design risk
**Recommendation**: your proposed approach", roles=["architect"], rounds=1)
Show output under "🏛 Phase 1/6 — Architect".
Extract HANDOFF_1: one sentence — "🏛 Architect: <Recommendation>"
Update session file: "- [ ] Phase 1" → "- [x] Phase 1 (HANDOFF_1)"; append to ## Findings.

### Phase 2 — Security
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

PRIOR FINDINGS:
<HANDOFF_1>

Structure your response:
**Findings**: threat surfaces or auth gaps
**Concerns**: highest-risk issue
**Recommendation**: required security measure", roles=["security"], rounds=1)
Show output under "🔒 Phase 2/6 — Security".
Extract HANDOFF_2: one sentence — "🔒 Security: <Concerns>"

### Phase 3 — Implementer
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

PRIOR FINDINGS:
<HANDOFF_1>
<HANDOFF_2>

Structure your response:
**Findings**: specific files or functions that need changing
**Concerns**: implementation difficulty or hidden cost
**Recommendation**: concrete implementation path", roles=["implementer"], rounds=1)
Show output under "⚙️ Phase 3/6 — Implementer".
Extract HANDOFF_3: one sentence — "⚙️ Implementer: <Recommendation>"

### Mid-Sprint Brief (print after Phase 3, before Phase 4)
  "── Mid-sprint brief ──"
  <HANDOFF_1>
  <HANDOFF_2>
  <HANDOFF_3>
  "── Continuing to tester, skeptic, moderator ──"

### Phase 4 — Tester
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

PRIOR FINDINGS:
<HANDOFF_1>
<HANDOFF_2>
<HANDOFF_3>

Structure your response:
**Findings**: edge cases and failure modes for the proposed implementation
**Concerns**: hardest thing to test or verify
**Recommendation**: test strategy and critical test cases", roles=["tester"], rounds=1)
Show output under "🧪 Phase 4/6 — Tester".
Extract HANDOFF_4: one sentence — "🧪 Tester: <Concerns>"

### Phase 5 — Skeptic (targeted challenger)
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

PRIOR FINDINGS:
<HANDOFF_1>
<HANDOFF_2>
<HANDOFF_3>
<HANDOFF_4>

Your job: challenge the architect's approach (<HANDOFF_1>) and the implementer's plan (<HANDOFF_3>) specifically. Find the weakest assumption in each. Do NOT give generic concerns — cite the specific proposals above.

Structure your response:
**Findings**: the weakest assumption in the architect's or implementer's proposal
**Concerns**: most likely failure mode if this proceeds as planned
**Recommendation**: what must change or be proven before starting", roles=["skeptic"], rounds=1)
Show output under "😈 Phase 5/6 — Skeptic".
Extract HANDOFF_5: one sentence — "😈 Skeptic: <Concerns>"

### Phase 6 — Moderator
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

FULL WAR ROOM BRIEF:
<HANDOFF_1>
<HANDOFF_2>
<HANDOFF_3>
<HANDOFF_4>
<HANDOFF_5>

Synthesize these findings. Make a clear recommendation.", roles=["moderator"], rounds=1)
Show output under "🎯 Phase 6/6 — Moderator".

### Final Synthesis (by you, Claude — no tool call)
Using all 6 phase outputs now in context:
  ✅ Agreed:        items all phases converged on
  ⚠️  Disputed:     live tensions (especially skeptic vs architect/implementer)
  ❓ Open questions: must-answer before starting
  🎯 Action plan:   3-5 concrete next steps

Update session file: status → completed.
Print: "✅ Session complete: <path>"
(If interrupted, run /jsat crack --continue to resume from the last incomplete phase.)

## Actions File

Extract the "🎯 Action plan: 3-5 concrete next steps" from the Final Synthesis.
Write ~/.jsat/sessions/crack-actions-<SLUG>-<YYYYMMDD-HHMM>.md with each step
as a "- [ ]" item (include exact file edits, commands, tests to run, decisions to log).

Print: "📋 Actions: <path>"

Execute each action item in sequence:
  1. Run the action
  2. Mark "- [ ]" → "- [x] (done: <result>)" in the file
  3. Continue to next
When all done: status → completed. Print: "✅ All actions complete: <path>"

## --single Flag
If --single: call jsat__crack(task=<task>) with all defaults (6 agents, 3 rounds).
Note: agents do not receive prior findings in single mode.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
