---
description: Multi-agent war room with artifact carry-forward — each agent builds on prior findings.
---

Parse $ARGUMENTS for optional flags:

  --phases N   → run in N phases (2-6, default: 6)
  --single     → run all agents at once (original one-shot behavior, may timeout)
  --continue   → resume the most recent in_progress crack session
  (no flag)    → 6-phase mode with artifact carry-forward (recommended)

If --phases N is given and N is not an integer in [2, 6]: do not silently clamp
or guess — say "invalid --phases value '<N>', must be 2-6" and default to 6
rather than proceeding with an undefined phase split.

## --continue Flag

When --continue is given:
  1. List ~/.jsat/sessions/crack-session-*.md ONLY (NOT crack-actions-*.md — the actions
     checklist file is a different artifact, also has a "status:" field and "- [ ]" items,
     and matching the old unqualified glob `crack-*.md` would grab it by mistake, resuming
     "phases" that are actually action-plan steps with a completely different format).
     Find the most recent crack-session file with status: in_progress.
  2. Read its frontmatter for `phases: N` (the split that was actually used — see Session
     File below, this is now recorded explicitly because reconstruction differs by split).
  3. Read the file; extract HANDOFF_<role> for every phase already marked "- [x]" from the
     ## Findings section, keyed by ROLE NAME (architect/security/implementer/tester/skeptic/
     moderator), not by phase number — a combined phase (used when N<6) produces MULTIPLE
     named handoffs from one phase slot, so "the handoff from phase 2" is ambiguous the
     moment phases combine roles; "the security agent's handoff" never is.
  4. Find the first phase slot with any unchecked role — resume execution from there, using
     every reconstructed HANDOFF_<role> exactly as that phase's template expects. A partial
     reconstruction (e.g. skipping straight to a later phase without every earlier role's
     handoff in hand) will silently degrade that phase's PRIOR FINDINGS block.
  5. Print: "▶ Resuming crack session: <filename> (phases=<N>, reconstructed handoffs from:
     <role list>)"

## Phased Mode (default)

Runs agents in the number of phases requested, splitting the 6 roles across N phase
slots. Each phase slot receives the original task PLUS a running brief of every
prior phase's key findings, keyed by role — agents build on each other's work
rather than operating in isolation. The skeptic specifically challenges the
architect's and implementer's proposals BY ROLE, regardless of which phase slot
those roles ended up in.

Phase splits (strip --phases flag; task = everything else):
  N=2: [architect,security,implementer] / [tester,skeptic,moderator]
  N=3: [architect,security] / [implementer,tester] / [skeptic,moderator]
  N=4: [architect] / [security,implementer] / [tester,skeptic] / [moderator]
  N=5: [architect] / [security] / [implementer] / [tester,skeptic] / [moderator]
  N=6 (default): one agent per phase — maximum granularity

### How a combined-role phase slot actually works (this was previously
unspecified for anything other than N=6 — every N<6 call was undefined behavior)

A phase slot with MULTIPLE roles (e.g. N=2's first slot: architect+security+
implementer) is ONE jsat__crack call with `roles=[<all roles in that slot>]` and
`rounds=1` — NOT three separate calls. The tool runs all listed roles internally
in that single call and returns one statement per role. Example for N=2's first
slot:

  jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

Structure EACH role's response separately:
**Findings**: what exists in the codebase relevant to this task
**Concerns**: top risk from this role's perspective
**Recommendation**: this role's proposed approach", roles=["architect","security","implementer"], rounds=1)

From the result's per-role statements, extract THREE separate handoffs —
HANDOFF_architect, HANDOFF_security, HANDOFF_implementer — one sentence each,
exactly as you would if they'd run as three separate phases. Show the combined
call's output under "🏛🔒⚙️ Phase 1/2 — Architect + Security + Implementer" (one
subsection per role within it, not a single merged paragraph — merging three
roles' distinct findings into one undifferentiated block loses the "who said
what" that later phases and the skeptic depend on).

The SECOND slot of every split (whatever combination of tester/skeptic/moderator
it contains) receives ALL FIVE prior handoffs (HANDOFF_architect through
HANDOFF_skeptic, whichever exist by that point) in its PRIOR FINDINGS block,
keyed by role name — same content as the 6-phase version's cumulative context,
just delivered in fewer, larger deliveries.

## Universal flag carry-through

If _BUDGET or _DASHBOARD were set by the universal flags preamble, add them to EVERY
jsat MCP tool call in every phase:
  - _BUDGET set      → add _budget=<N> to every jsat__* call
  - _DASHBOARD True  → add _dashboard=True AND _dashboard_session="crack" to every call
                       (all phase calls share ONE browser tab at …/jsat/dashboard/crack)
Example: /jsat crack timeout=300 dashboard=true <task>
  → every call: jsat__crack(..., _budget=300, _dashboard=True, _dashboard_session="crack")

## Phase 0 — Codebase Context (run before Phase 1)

Call: jsat__get_index_status()
Call: jsat__list_services()
Build CONTEXT_BRIEF from the results: node count, edge count, top service names.
Prepend CONTEXT_BRIEF to every agent's task for grounding.

Create session file: ~/.jsat/sessions/crack-session-<SLUG>-<YYYYMMDD-HHMM>.md
(named with the `crack-session-` prefix, distinct from the `crack-actions-` prefix used
below, so --continue's glob can never confuse a war-room session with an actions checklist)
Content:
  ---
  skill: crack
  task: <original task>
  phases: <N — the actual split in use, 2-6>
  status: in_progress
  ---
  ## Steps
  - [ ] <phase slot 1: role or role+role+role list>
  ...
  ## Findings
  (empty)
Print: "📄 Session: <path>"

## AI Backend Check (apply after EVERY jsat__crack call in every phase below,
including combined-role calls — a combined call can be entirely templated
boilerplate for ALL its roles at once, which is a bigger single-call blast
radius than a lone-role phase failing)

jsat__crack needs a working AI backend to produce real multi-agent reasoning. If the
response has ai_available:false, or reads as generic templated boilerplate with no
concrete reference to the task/codebase (e.g. placeholder text like "the architect
would assess design tradeoffs here" instead of an actual assessment) for ANY role in
the call, treat that ENTIRE phase slot's output as INVALID, not as a real handoff:
  - Do NOT extract a HANDOFF_<role> from a placeholder response — feeding fabricated
    content forward would silently poison every later phase's PRIOR FINDINGS block,
    and the moderator's final synthesis would be built on fiction.
  - Print: "⚠️ Phase <slot>/<N> — AI backend unavailable, response is a placeholder,
    not real analysis. Run `/jsat doctor` to check the AI provider, or `jsat ai use
    <provider>` to switch, then retry this phase."
  - Update the session file to leave that phase unchecked (do not mark "- [x]") so
    --continue will retry it once the backend is fixed, and STOP the war room rather
    than cascading through remaining phases on top of a broken foundation.

## War Room Phases (6-phase / N=6 templates — for N<6, combine per the "combined-role
phase slot" section above, keeping each role's own Structure block and extracting one
HANDOFF_<role> per role regardless of how many roles share a call)

### Phase 1 — Architect
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

Structure your response:
**Findings**: what exists in the codebase relevant to this task
**Concerns**: top design risk
**Recommendation**: your proposed approach", roles=["architect"], rounds=1)
Show output under "🏛 Phase 1/6 — Architect".
Extract HANDOFF_architect: one sentence — "🏛 Architect: <Recommendation>"
Update session file: "- [ ] Phase 1" → "- [x] Phase 1 (HANDOFF_architect)"; append to ## Findings.

### Phase 2 — Security
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

PRIOR FINDINGS:
<HANDOFF_architect>

Structure your response:
**Findings**: threat surfaces or auth gaps
**Concerns**: highest-risk issue
**Recommendation**: required security measure", roles=["security"], rounds=1)
Show output under "🔒 Phase 2/6 — Security".
Extract HANDOFF_security: one sentence — "🔒 Security: <Concerns>"

### Phase 3 — Implementer
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

PRIOR FINDINGS:
<HANDOFF_architect>
<HANDOFF_security>

Structure your response:
**Findings**: specific files or functions that need changing
**Concerns**: implementation difficulty or hidden cost
**Recommendation**: concrete implementation path", roles=["implementer"], rounds=1)
Show output under "⚙️ Phase 3/6 — Implementer".
Extract HANDOFF_implementer: one sentence — "⚙️ Implementer: <Recommendation>"

### Mid-Sprint Brief (print after Phase 3, before Phase 4)
  "── Mid-sprint brief ──"
  <HANDOFF_architect>
  <HANDOFF_security>
  <HANDOFF_implementer>
  "── Continuing to tester, skeptic, moderator ──"

### Phase 4 — Tester
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

PRIOR FINDINGS:
<HANDOFF_architect>
<HANDOFF_security>
<HANDOFF_implementer>

Structure your response:
**Findings**: edge cases and failure modes for the proposed implementation
**Concerns**: hardest thing to test or verify
**Recommendation**: test strategy and critical test cases", roles=["tester"], rounds=1)
Show output under "🧪 Phase 4/6 — Tester".
Extract HANDOFF_tester: one sentence — "🧪 Tester: <Concerns>"

### Phase 5 — Skeptic (targeted challenger)
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

PRIOR FINDINGS:
<HANDOFF_architect>
<HANDOFF_security>
<HANDOFF_implementer>
<HANDOFF_tester>

Your job: challenge the ARCHITECT'S approach (<HANDOFF_architect>) and the
IMPLEMENTER'S plan (<HANDOFF_implementer>) specifically — reference these two
handoffs BY ROLE, never by a positional label like "phase 1" or "phase 3". In
combined-role phase splits (--phases 2-5), the architect's and implementer's
handoffs may have come from the SAME phase slot as other roles, or even the same
slot as each other — the role name is the only stable identifier across every
--phases value; a phase-number reference that happened to be correct in 6-phase
mode is silently wrong in every other split. Find the weakest assumption in each.
Do NOT give generic concerns — cite the specific proposals above.

Structure your response:
**Findings**: the weakest assumption in the architect's or implementer's proposal
**Concerns**: most likely failure mode if this proceeds as planned
**Recommendation**: what must change or be proven before starting", roles=["skeptic"], rounds=1)
Show output under "😈 Phase 5/6 — Skeptic".
Extract HANDOFF_skeptic: one sentence — "😈 Skeptic: <Concerns>"

### Phase 6 — Moderator
Call: jsat__crack(task="<task>

CODEBASE: <CONTEXT_BRIEF>

FULL WAR ROOM BRIEF:
<HANDOFF_architect>
<HANDOFF_security>
<HANDOFF_implementer>
<HANDOFF_tester>
<HANDOFF_skeptic>

Synthesize these findings. Make a clear recommendation.", roles=["moderator"], rounds=1)
Show output under "🎯 Phase 6/6 — Moderator".

### Final Synthesis (by you, Claude — no tool call)
Using all role outputs now in context (regardless of how many phase slots they
were spread across):
  ✅ Agreed:        items all roles converged on
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
Note: agents do not receive prior findings in single mode — this is a materially
weaker mode of the tool (no carry-forward, no role-targeted skeptic), not just a
faster version of the same result; only use it when speed matters more than the
carry-forward quality the phased mode exists to provide, and say so if the user
seems to expect phased-mode depth from a --single run.

## Budget & Timing
crack has a 55s soft budget PER CALL. A combined-role phase slot (--phases 2-4)
does not get a proportionally larger budget just because it's doing more roles'
worth of work in one call — if a 3-role combined call is timing out where a
single-role call wouldn't, that is a signal to use a higher --phases count (more,
smaller calls) rather than raising --timeout indefinitely on a call that's
structurally doing 3x the reasoning in one budget window.
Override: /jsat crack timeout=300 <task>
When the soft budget is exceeded:
  ⏱ progress notification (mid-call): crack is still running — wait unless you need to skip
  ⏱ _slow in response: completed after budget — result is valid
  ⛔ _hard_timeout in response: force-killed at 5× budget — retry with a HIGHER --phases
     count (smaller, more numerous calls) or --single, not just a bigger --timeout
Default phased mode (6 phases) is the most reliable for large tasks because each phase
runs within its own budget window. Use --phases 2 only when the task is simple enough
that combined-role calls are unlikely to strain the per-call budget.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
