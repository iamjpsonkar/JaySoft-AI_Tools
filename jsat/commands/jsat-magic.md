---
description: AI-orchestrated skill composer — analyzes any task and dynamically selects, orders, and runs the optimal JSAT skills to complete it.
---

Analyze the task, compose the optimal JSAT skill sequence from the full catalog,
run each skill adaptively, and converge when the task is complete.

Parse $ARGUMENTS for optional flags:
  --depth quick     → cap at 4 skills (fast pass, breadth-first)
  --depth standard  → cap at 8 skills (default, balanced)
  --depth deep      → cap at 15 skills (comprehensive)
  --budget N        → explicit cap on skill invocations
  --service <name>  → scope all skills to one service (avoids timeout)
  --preview         → compose plan only, do NOT run any skills
  --continue        → resume the most recent in_progress magic session
  (no flag)         → standard depth, auto-scoped

## --continue Flag

When --continue is given:
  1. List files in ~/.jsat/sessions/ matching magic-*.md
  2. Find the most recent file with "status: in_progress" in its frontmatter
  3. Read it and print: "▶ Resuming: <filename>"
  4. Extract task from frontmatter; extract findings from ## Findings as accumulated context
  5. Find first "- [ ]" step — resume execution from there
  6. Skip all "- [x]" steps (already done)
  7. Continue with Step 3 execution, carrying findings as prior context

## Step 1 — Analyze the task

Read the task description and extract:
  - WHAT: what is being asked? (question / change / investigation / decision)
  - WHERE: specific files, functions, services, or broad scope?
  - RISK: does this involve security, data, production, or breaking changes?
  - DEPTH: how complete an answer is needed?

## Step 2 — Compose the skill sequence

Select skills from this layered catalog, ordered by information dependency.
Select only what the task genuinely needs — minimum sufficient set.
Prefer narrow fast skills before heavy ones (crack, sprint only if genuinely complex).

  LAYER 0 — Context (always run):
    status, list-services

  LAYER 1 — Discover (when task names symbols or asks where/what/how):
    find-function, find-class, trace, query, smart, short, recent, list-endpoints

  LAYER 2 — Analyze (when task involves risk, impact, quality, or incidents):
    blast-radius, security, test-gaps, coverage, contract, cohesion, migration, incident

  LAYER 3 — Plan (when task involves building, deciding, or designing):
    lazy, plan, think, crack, decide, knowledge

  LAYER 4 — Execute (when task involves implementing or reviewing):
    review, prompt, sprint

  LAYER 5 — Verify (after execution, before shipping):
    test-gaps --generate, blast-radius --severity breaking

  LAYER 6 — Record (at end, for operational or architectural work):
    decide log, reflect, knowledge-add, runbook

If --service was given, pass service_filter=<name> (or service=<name> where supported)
to ALL Layer 1-5 tool calls: blast_radius, query, test-gaps, coverage, security, incident.
This is the primary mechanism for preventing timeouts on large repos.

Announce the composed plan before running:
  "✨ Magic Plan (<N> skills, <depth> depth):"
  "  Layer 0: status → list-services"
  "  Layer 1: <selected discover skills with params>"
  "  Layer 2: <selected analyze skills>"
  (only list layers that have selected skills)

If --preview: STOP here, do not run any tools.

## Session File

Before running any skills, create the session directory and file:

  mkdir -p ~/.jsat/sessions/
  SLUG = first 4 words of task, lowercased, spaces→hyphens
  FILE = ~/.jsat/sessions/magic-<SLUG>-<YYYYMMDD-HHMM>.md

Write the file:
  ---
  skill: magic
  task: <original task>
  created: <current datetime>
  status: in_progress
  ---

  ## Steps
  - [ ] <each selected skill, one line each>

  ## Findings
  (populated as steps complete)

Print: "📄 Session: ~/.jsat/sessions/<filename>"

## Step 3 — Execute adaptively

CRITICAL: Use ONLY jsat__* MCP tools for every skill step.
  NEVER use Bash, Read, Explore, WebSearch, or other native tools as substitutes.
  jsat tools have full graph access; native tools do not. No exceptions.

Universal flag carry-through: if _BUDGET or _DASHBOARD were set by the universal flags
preamble, add them to EVERY jsat MCP tool call in this section:
  - _BUDGET set      → add _budget=<N> to every tool call
  - _DASHBOARD True  → add _dashboard=True AND _dashboard_session="magic" to every tool call
                       (all calls share ONE browser tab at …/jsat/dashboard/magic)
Example: /jsat magic timeout=300 dashboard=true <task>
  → every tool call: jsat__query(question='...', _budget=300, _dashboard=True,
                                 _dashboard_session="magic")
  → first tool call opens the browser tab; all subsequent calls stream into the same tab

For each selected skill in layer order:
  1. Print: "▶ [Layer N] <skill> — <what it checks for this specific task>"
  2. Call the corresponding JSAT MCP tool with task-specific parameters
     (append _budget and _dashboard if set — see carry-through rules above)
  3. Show result under: "✅ <skill>: <1-sentence finding>"
  4. ADAPT: if the finding reveals new information needs, add skills from later layers
     (example: blast-radius shows breaking changes → add test-gaps --generate to Layer 5)
  5. CONVERGE: if the task is now answerable with high confidence, skip remaining skills
     and jump to synthesis. Print: "⚡ Converged at step N/M — sufficient to answer."
  6. Update session file: change "- [ ] <skill>" → "- [x] <skill> (finding: <1-sentence>)"
     and append to ## Findings: "**<skill>:** <1-sentence finding>"

Timeout handling: all JSAT tools have soft budgets (notification-only) and hard limits (5× soft).
  Pass timeout=<N> to override the soft budget for the entire magic run:
    /jsat magic timeout=300 investigate the payment flow  → soft budget 300s per tool
  ⏱ SLOW NOTIFICATION (via progress notification while running):
     The tool exceeded its soft budget but is STILL RUNNING. Last steps are reported.
     Decide: wait / skip / split / optimize. The result will arrive.
  ⏱ SLOW COMPLETED (in response, _slow=true):
     The tool finished after its soft budget. Result is valid; consider scoping future calls.
  ⛔ HARD TIMEOUT (in response, _hard_timeout=true):
     The tool was force-killed after 5× the soft budget. No result. MUST act:
     1. Read the "💡 Suggestion" line — retry with narrower scope
     2. Read the "🤖 AI Guidance" — split or skip
     3. Re-call with service_filter + reduced max_depth, OR skip
     4. If still hitting hard timeout: break into separate /jsat magic calls per service
  🔁 DEPTH EXCEEDED (in response, _depth_exceeded=true):
     Too many nested tool calls. Break into separate tasks.

Blast-radius calls in magic default to max_depth=3 (not 5). Pass --depth deep to the
blast-radius sub-call if you need deeper traversal on a fast repo.

## Step 4 — Synthesize

  ✨ **Magic Summary**
  - Task: <original task>
  - Skills used: <N of planned>
  - Key findings: <one bullet per skill with useful data>
  - Answer: <direct, complete answer to the task>
  - Actions: <1-3 concrete next steps>
  - Log a decision? <yes/no — if yes: /jsat decide log <decision>>
  - Record outcome? <yes/no — if yes: /jsat reflect <outcome>>

Update session file frontmatter: status → completed.
Print: "✅ Session complete: ~/.jsat/sessions/<filename>"
(If interrupted before this step, run /jsat magic --continue to resume.)

## Actions File

Extract every concrete action from the summary above (commands to run, files
to edit with line:column, tests to verify, commits to make). Write:
  ~/.jsat/sessions/magic-actions-<SLUG>-<YYYYMMDD-HHMM>.md

File format:
  ---
  skill: magic
  task: <original task>
  generated: <datetime>
  status: pending
  ---
  ## Action Items
  - [ ] <exact command or file edit>  — <why>
  ...
  ## Completed Actions
  (empty)

Print: "📋 Actions: <path>"

Now read that file and execute each "- [ ]" action in sequence:
  1. Execute the action (run command, edit file, install package, etc.)
  2. Update the file: "- [ ]" → "- [x] (done: <result>)"
  3. Append to ## Completed Actions: "<action>: <result>"
  4. Continue to next action

When all actions are done: set status → completed in the actions file.
Print: "✅ All actions complete: <path>"


HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
