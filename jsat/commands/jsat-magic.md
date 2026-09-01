---
description: AI-orchestrated skill composer — analyzes any task and dynamically selects, orders, and runs the optimal JSAT skills to complete it.
---

Analyze the task, compose the optimal JSAT skill sequence from the full catalog,
run each skill adaptively, and converge when the task is complete.

Parse $ARGUMENTS for optional flags:
  --depth quick     → cap at 4 skills (fast pass, breadth-first)
  --depth standard  → cap at 8 skills (default, balanced)
  --depth deep      → cap at 15 skills (comprehensive)
  --budget N        → explicit cap on skill invocations (overrides --depth's cap)
  --service <name>  → scope all skills to one service (avoids timeout)
  --preview         → compose plan only, do NOT run any skills
  --continue        → resume the most recent in_progress magic session
  (no flag)         → standard depth, auto-scoped

## --continue Flag

When --continue is given:
  1. List files in ~/.jsat/sessions/ matching magic-*.md (but NOT magic-actions-*.md
     — that is a different artifact with its own "- [ ]" format; matching it by
     mistake would resume an actions checklist as if it were a skill-selection plan).
  2. Find the most recent file with "status: in_progress" in its frontmatter.
  3. Read it and print: "▶ Resuming: <filename>".
  4. Extract task from frontmatter; extract findings from ## Findings as accumulated context.
  5. CATALOG-DRIFT CHECK (do this before resuming any step): the live skill catalog
     can change between sessions — skills get removed/renamed when the command set
     is refactored (this has already happened once this session: think, reflect,
     knowledge-add, and token-budget were removed and folded into other commands).
     For every remaining "- [ ]" step, confirm the named skill still has a
     matching "## <name>" section in the current dispatcher. If one doesn't:
       - If its function was folded into another command (check that command's
         description for an obvious successor — e.g. a removed "token-budget"
         step becomes "tokens --model"), substitute the successor and note the
         substitution in ## Findings: "**<old-skill>:** superseded by <new-skill>,
         substituted on resume."
       - If no obvious successor exists, mark the step "- [x] <skill> (SKIPPED —
         no longer in catalog, no successor found)" and continue to the next step
         rather than failing the whole resume.
  6. Find first remaining "- [ ]" step — resume execution from there.
  7. Skip all "- [x]" steps (already done or already resolved by the drift check).
  8. Continue with Step 3 execution, carrying findings as prior context.

## Step 1 — Analyze the task

Read the task description and extract, explicitly, in this order (Step 2 depends
on all four of these — this is not just descriptive framing):
  - WHAT: what is being asked? (question / change / investigation / decision)
  - WHERE: specific files, functions, services, or broad scope?
  - RISK: does this involve security, data, production, or breaking changes?
    Classify as one of: none / moderate / HIGH. HIGH = anything touching auth,
    payments, migrations, deletions, or explicitly described as
    production-facing. This value is a HARD CONSTRAINT on Step 2, not advisory.
  - DEPTH: how complete an answer is needed? shallow (quick fact) / normal /
    thorough (the user explicitly wants comprehensive coverage).

Print these four classifications before moving to Step 2 — they are inputs to
a mechanical rule in Step 2, not just narrative color, so the user (and you,
re-reading your own output later) can verify Step 2's selection actually
followed from them.

## Step 2 — Discover the live catalog, then compose the skill sequence

### 2a — Discover (never hardcode the catalog)

Do NOT rely on a fixed, hardcoded list of skill names — that goes stale every
time a command is added to or removed from jsat/commands/ (proven this session:
the catalog shrank from 50 to 46 files mid-conversation when duplicates were
clubbed together). Instead, discover the catalog from the same source every
/jsat invocation already uses: the "## help" table at the top of THIS dispatcher
file lists every currently installed `/jsat <name>` command with its one-line
description, regenerated fresh from jsat/commands/jsat-*.md every time
`jsat connect claude` runs. Read that table now — it IS the live catalog. Never
enumerate skills by name from memory or from an example list in this file; an
example is illustrative of the CLASSIFICATION METHOD, not an exhaustive roster.

### 2b — Exclude orchestrators from auto-selection

Before classifying anything into a layer, remove these from the candidate pool
entirely — detect them by description text containing "orchestrat", "war room",
"workflow advisor", "delivery workflow", or "skill composer" (this catches magic,
aw, crack, and sprint by pattern, not by hardcoded name, so a future orchestrator
skill is caught too):
  - Never auto-select an orchestrator skill as a layer member. Composing magic's
    own plan out of OTHER orchestrators risks silent recursive/nested runs (magic
    selecting aw, which itself runs a 4-5 step sequence magic has no visibility
    into or budget accounting for) with no depth guard beyond the generic
    MCP-level "DEPTH EXCEEDED" protection, which fires too late to be a good UX.
  - Orchestrators are ESCALATION OPTIONS, not layer members: if, after building
    the plan from Layers 0-6/G, the task still looks too complex for the composed
    sequence to handle (e.g. it's fundamentally a multi-perspective design debate,
    not a lookup-then-verify task), say so explicitly and suggest the user invoke
    the appropriate orchestrator directly ("this looks like it needs /jsat-crack's
    multi-agent debate, not a linear skill sequence — want me to run that
    instead?") rather than magic quietly trying to drive it via jsat__crack itself
    as if it were an ordinary Layer 3 tool call.

### 2c — Classify remaining skills into layers by description, not name

Classify each discovered skill into a layer by matching its description text
against these rules (a rule like "description mentions impact/coverage/security"
keeps working when a new analyzer skill is added tomorrow; a hardcoded name list
does not):

  LAYER 0 — Context (always run): description mentions "index status" or
    "list ... services"/"list ... endpoints" scoped to codebase inventory
  LAYER 1 — Discover (task names symbols or asks where/what/how): description
    mentions "find", "trace", "answer", "briefest", "compression", "recent changes"
  LAYER 2 — Analyze (task involves risk, impact, quality, incidents, dependencies):
    description mentions "impact", "security", "test", "coverage", "contract",
    "cohesion", "migration", "incident", "dead code", "dependency", "health"
  LAYER 3 — Plan (task involves building, deciding, designing): description
    mentions "reuse", "planning", "forcing questions", "decision journal",
    "knowledge base" (query/search variants, not the -add variant)
  LAYER 4 — Execute (task involves implementing or reviewing): description
    mentions "review", "pipeline" — EXCLUDING anything already removed as an
    orchestrator in 2b
  LAYER 5 — Verify (after execution, before shipping): description mentions
    "verify", "prove", "generating tests", "breaking-change check"
  LAYER 6 — Record (wrap-up, operational/architectural artifacts): description
    mentions "log", "add an entry", "runbook", "changelog", "PR description"
  LAYER G — Mutates git state, NEVER auto-select: description or command name
    matches a git-mutation verb (merge, rebase, cherry-pick, checkout, reset,
    commit, push) — detected by pattern match against the live catalog so a
    future git-mutating skill is automatically caught without editing this file.
    Only select from Layer G when the task EXPLICITLY names the operation
    ("merge X into Y", "rebase onto main") — "prepare this for merge" means
    Layer 4-6, not Layer G; it is not asking magic to perform a merge.

  LAYER W — Reaches the live internet, NOT auto-selected by default: description
    mentions "internet"/"live internet" (currently: internet). This is the
    one skill in the whole catalog whose own file explicitly authorizes WebSearch/
    WebFetch — see 2f below for the CRITICAL-rule interaction. Select it only when
    the task's own wording needs information this codebase's graph cannot contain:
    a current library version, a public CVE, official upstream docs, "what does
    everyone else do" best-practice framing, or anything explicitly phrased as
    needing up-to-date/external info. A task about THIS repo's own code never
    needs Layer W on its own — Layers 0-6 already cover that; only add Layer W
    alongside them when the task also references something external.

### 2f — The Layer W exception to "jsat__* tools only"

Step 3's CRITICAL rule ("use ONLY jsat__* MCP tools... NEVER WebSearch") governs
every OTHER layer without exception. The moment Layer W is selected, that rule
narrows for that one step only: internet's own file (jsat-internet.md) is
the sole sanctioned caller of WebSearch/WebFetch in the whole catalog, and magic
must let it do so rather than trying to force it through a jsat__* substitute
that cannot reach the internet. Do not extend this narrowing to any other
selected skill in the same run — every other step in the same magic invocation
still follows the unqualified CRITICAL rule.

### 2d — Wire Step 1's classification into selection (this is the part that was
previously missing: Step 1 extracted RISK/DEPTH but nothing consumed them)

  - If RISK = HIGH: Layer 2's security AND impact-analysis skills (description
    matches "security" or "impact") are MANDATORY, not optional — select them
    even if the task's own wording doesn't obviously ask for them. A task like
    "add a new field to the payments table" doesn't say "check security," but
    RISK=HIGH from touching payments means Layer 2 security/impact runs anyway.
  - If RISK = HIGH: Layer 5 verify is MANDATORY at the end regardless of how
    confident Step 3's CONVERGE check feels — see 3e, this overrides convergence.
  - If DEPTH = shallow: cap the plan at Layer 0 + Layer 1 unless RISK=HIGH forces
    more; do not run Layer 3/4 planning machinery for a quick factual question.
  - If DEPTH = thorough: do not let --depth quick's 4-skill cap silently truncate
    coverage — if the user's own wording asks for comprehensive analysis, treat
    that as at least --depth standard even if the flag wasn't explicitly passed.

Select only what the task genuinely needs beyond what 2d makes mandatory —
minimum sufficient set on top of the mandatory floor. Prefer narrow fast skills
before heavy ones.

If a Layer G skill is ever selected, print an explicit confirmation line before
running it ("This will run /jsat <skill>, which mutates git state — confirm
before I proceed") and wait for the user, even outside --preview mode — Layer G
is the one layer where "converge and run" does not apply blindly.

### 2e — Over-budget truncation order

If the naturally-selected set (mandatory floor from 2d + task-driven picks)
exceeds --depth's cap or an explicit --budget N, truncate in this priority order
(drop from the BOTTOM of this list first, never from the top):
  1. Layer 0 (never drop — near-zero cost, always needed for grounding)
  2. Anything 2d marked mandatory (RISK-driven security/impact/verify)
  3. Layer 2 (the task's own analysis needs)
  4. Layer 1 (discovery)
  5. Layer 3 (planning)
  6. Layer 6 (record) — usually fine to skip and suggest as a manual follow-up
  7. Layer 4/5 beyond what 2d already made mandatory
  8. Layer W (internet) — drop before any of the above if over budget; it is
     always supplementary, never load-bearing for answering the task itself
State explicitly which skills were dropped and why when truncation happens —
"dropped <skill> (Layer N) to fit --depth quick's 4-skill cap" — do not just
silently run a shorter list than what was composed.

Several jsat__* tools need an AI backend (query, prompt_optimize-derived flows,
crack, ithinking's plan/reflect are NOT AI-backed — see jsat-ithinking.md);
if an AI-backed tool is unconfigured/down it returns "[AI unavailable]" — this is
common, not an edge case. When that happens: fall back to the AI-free tools that
cover the same ground (blast_radius, security_review, list_services/list_endpoints
are all pure graph/static analysis and do not need AI), and say explicitly in the
summary that a step ran degraded rather than silently presenting a thinner answer
as complete.

Layer W fails differently: WebSearch/WebFetch are native tools, not AI-backed
jsat__* tools, so they never return "[AI unavailable]" — if unavailable, the tool
call itself is rejected or errors, or WebSearch's US-only gating simply blocks
it. jsat-internet.md's own Step 0 handles this by falling back to jsat__query
alone; magic does not need separate handling beyond noting in the summary that
the external half of a Layer W result ran degraded if that fallback fired.

If --service was given, pass service_filter=<name> (or service=<name> where
supported) to ALL Layer 1-5 tool calls: blast_radius, query, test-gaps, coverage,
security, incident. This is the primary mechanism for preventing timeouts on
large repos.

Announce the composed plan before running:
  "✨ Magic Plan (<N> skills, <depth> depth):"
  "  Risk: <none/moderate/HIGH> — Depth: <shallow/normal/thorough>"
  "  Layer 0: status → list-services"
  "  Layer 1: <selected discover skills with params>"
  "  Layer 2: <selected analyze skills> <(mandatory: security/impact) if RISK=HIGH forced them>"
  "  Layer W: internet <query> (reaches the live internet — see jsat-internet.md)"
  (only list layers that have selected skills; note any 2e truncation here too;
   Layer W only appears when the task genuinely needs external/current info)

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
  risk: <none/moderate/HIGH>
  depth: <shallow/normal/thorough>
  ---

  ## Steps
  - [ ] <each selected skill, one line each>

  ## Findings
  (populated as steps complete)

Print: "📄 Session: ~/.jsat/sessions/<filename>"

## Step 3 — Execute adaptively

CRITICAL: Use ONLY jsat__* MCP tools for every skill step.
  NEVER use Bash, Read, Explore, WebSearch, or other native tools as substitutes.
  jsat tools have full graph access; native tools do not. The ONE exception: if
  Layer W (internet) was selected in Step 2, that step's own file
  (jsat-internet.md) is authorized to call WebSearch/WebFetch directly — see 2f.
  No other step in this run gets that exception.

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
  4. ADAPT: if the finding reveals new information needs, add skills from later
     layers (example: blast-radius shows breaking changes → add test-gaps
     --generate to Layer 5). When you add a skill this way, ALSO append it to the
     session file's ## Steps list as a new "- [ ] <skill> (added adaptively after
     <triggering-skill>)" line immediately — not just to ## Findings — so a
     --continue after an interruption knows about it. An adaptively-added step
     that only lives in prose findings and never reaches the checklist is
     invisible to resume logic and will silently vanish on --continue.
  5. CONVERGE — concrete rubric, not vibes (ALL THREE must hold, not just "feels
     complete"):
       a. The WHAT extracted in Step 1 has been directly answered by at least one
          concrete tool result (not inferred from absence of findings).
       b. No Layer 2 result flagged a "breaking"/"critical"/"high" finding that
          hasn't been either resolved by a later step or explicitly carried
          into the final summary as an open risk.
       c. If RISK was classified HIGH in Step 1, Layer 5 verify has actually run
          — a high-risk task never converges early just because the answer
          "seems" complete; mandatory verify cannot be skipped by convergence.
     If all three hold: skip remaining skills and jump to synthesis. Print:
     "⚡ Converged at step N/M — <a, b, c> all satisfied."
     If the task felt answerable but (b) or (c) blocks convergence, say so
     explicitly rather than converging anyway: "Answer looks complete but <b/c>
     is not yet satisfied — continuing to <next skill>."
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
  - Risk / Depth: <as classified in Step 1>
  - Skills used: <N of planned> (<N> dropped by 2e truncation, if any)
  - Key findings: <one bullet per skill with useful data>
  - Answer: <direct, complete answer to the task>
  - Open risks not yet resolved: <anything from CONVERGE rubric (b) still open — say "none" if clean>
  - Actions: <1-3 concrete next steps>
  - Log a decision? <yes/no — if yes: /jsat decide log <decision>>
  - Record outcome? <yes/no — if yes: /jsat ithinking reflect subtask=<outcome>>

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
