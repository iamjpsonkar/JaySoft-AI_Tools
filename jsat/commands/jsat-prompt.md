---
description: Discuss → Plan → Execute → Verify → Synthesize — uses the right tool per query type and checks its own answers.
---

Parse $ARGUMENTS for optional flags:

  --rewrite or --agent  → Phase 1 optimizer: jsat__prompt_rewrite  (1 LLM agent)
  --agents              → Phase 1 optimizer: jsat__prompt_multi_agent (3 parallel agents)
  (no optimizer flag)   → Phase 1 optimizer: jsat__prompt_optimize (offline, fastest)
  --diff                → ALSO show raw vs optimized diff after Phase 1
  --optimize-only       → Stop after Phase 1; show optimized prompt only
  --phases N            → Run N phases (2-6, default: 6)
  --service <name>      → Scope all query phases to this one service
  --single              → Original one-shot flow (optimize → one jsat__query call)
  --continue            → Resume most recent in_progress prompt session

## --continue Flag

When --continue is given:
  1. List ~/.jsat/sessions/prompt-*.md; find most recent with status: in_progress
  2. Read it; extract optimized_prompt from ## Findings if Phase 1 completed
  3. Find first "- [ ]" phase — resume from there with saved context
  4. Print: "▶ Resuming prompt session: <filename>"

The query is every word that is NOT a flag. Strip all flags; join the rest.
Priority when multiple optimizer flags: --agents beats --rewrite.

## AI-Backend Degradation (applies to every phase below)

This command leans heavily on LLM-backed tools: jsat__query (general lookups,
Phase 3/4), jsat__prompt_rewrite / jsat__prompt_multi_agent (--rewrite/--agents),
jsat__investigate_incident, and jsat__short (Phase 5 fallback). ALL of these
depend on a live AI provider (e.g. Ollama) and will return a string starting
with "[AI unavailable" instead of raising an error when the provider is down —
this is common, not an edge case. jsat__prompt_optimize (the default, flagless
optimizer) and the pure graph tools (jsat__get_index_status, jsat__list_services,
jsat__get_function, jsat__get_class, jsat__trace_call_chain, jsat__get_test_gaps)
are NOT AI-backed and remain reliable even when the provider is down.

Whenever ANY tool call returns "[AI unavailable" text:
  1. Do NOT retry with another AI-backed tool as a "fallback" — that just
     produces a second identical failure (e.g. jsat__query → jsat__query,
     or jsat__short → jsat__short, are no-ops, not fallbacks).
  2. Set a session-wide DEGRADED flag and record which phase/tool first hit it.
  3. Fall back to the non-AI graph tools directly for that phase's data need
     (see per-phase notes below) and answer using YOUR OWN reasoning (you are
     already an LLM) over the raw graph data instead of asking jsat__query to
     reason for you.
  4. Report the degradation explicitly in the final answer — never silently
     present a partial or empty AI-dependent result as if it were complete.

## Phased Mode (default, --phases 6)

Run in 6 sequential phases. Show output after each.

### Session File (before Phase 1)
Create ~/.jsat/sessions/prompt-<SLUG>-<YYYYMMDD-HHMM>.md with phases 1-6 as unchecked steps.
Print: "📄 Session: <path>"

### Phase 1 — Discuss + Optimize (~6s)

STEP A — Discuss (before optimizing):
Classify the query type from the question text:
  structural → contains "what calls", "who calls", "callers", "trace", "call chain"
  lookup     → contains "where is", "find function", "find class", "locate"
  security   → contains "security", "auth", "vulnerability", "secrets", "CVE"
  incident   → contains "failing", "error", "500", "broken", "bug"
  coverage   → contains "untested", "test gaps", "coverage"
  general    → everything else

Select the primary execution tool for Phase 3:
  structural → jsat__trace_call_chain
  lookup     → jsat__get_function or jsat__get_class
  security   → jsat__security_review
  incident   → jsat__investigate_incident
  coverage   → jsat__get_test_gaps
  general    → jsat__query

Print: "🗣 Query type: <type> — primary tool: <tool>"

STEP B — Optimize:
Call the optimizer selected by flags with query=<stripped text>.
If --rewrite/--agents was requested and the result is "[AI unavailable...":
  the LLM optimizer failed — fall back to jsat__prompt_optimize (offline, no AI
  dependency) instead, and tell the user the requested agent-based rewrite could
  not run so an offline optimization was used instead. Do NOT retry the same
  LLM-backed optimizer.
Read `optimized_prompt`. Save for all subsequent phases.
Show: optimized prompt, tokens before→after.
If --diff: also call jsat__prompt_diff and show diff (this itself may be
  AI-backed for the "optimized" side). This MUST match /jsat-prompt-diff's own
  fallback contract exactly — do not improvise a different recovery here:
  if it reports "[AI unavailable...": call jsat__prompt_optimize (offline,
  non-AI) fresh with the same stripped query text and use ITS output as the
  "AI received" panel, labeled "AI received (offline fallback — AI-backed
  optimizer unavailable)" — the identical label /jsat-prompt-diff uses. Do NOT
  assume Phase 1's already-computed optimized_prompt can stand in for this:
  that shortcut only happens to be correct when Phase 1 also used the
  flagless default (jsat__prompt_optimize); if Phase 1 ran with --rewrite or
  --agents, its optimized_prompt came from a DIFFERENT AI-backed tool and
  reusing it here would silently mix two unrelated optimizer outputs into one
  diff. Always call jsat__prompt_optimize fresh for this fallback, regardless
  of which optimizer Phase 1 used.
If --optimize-only: STOP here.
Label: "🔧 Phase 1/6 — Discuss + Optimize"

### Phase 2 — Plan + Scope (~3s)
Call: jsat__get_index_status()
Call: jsat__list_services()
Show: node/edge counts, service list.
State the query plan: "Plan: use <primary_tool> on <service>, then <secondary>."
Identify 1-2 most relevant services for Phase 3-4.
Label: "📊 Phase 2/6 — Plan + Scope"

### Phase 3 — Execute (Primary) (~15s)
Use the primary tool identified in Phase 1:
  structural: jsat__trace_call_chain(symbol=<key_symbol_from_question>)
  lookup:     jsat__get_function(name=<name>) or jsat__get_class(name=<name>)
  security:   jsat__security_review(path=<service_path or ".">)
  incident:   jsat__investigate_incident(description=<optimized_prompt>)
  coverage:   jsat__get_test_gaps(path=<service_path or ".">)
  general:    jsat__query(question=<optimized_prompt>, service=<primary_service>)

If --service was given, use it for all service-scoped calls.
If the primary tool is jsat__query or jsat__investigate_incident and it returns
"[AI unavailable...": do NOT fall back to jsat__query (same failure mode) or to
jsat__short (also AI-backed, see Phase 5). Instead set DEGRADED and gather raw
material yourself: jsat__get_index_status(), jsat__list_services(), and — for
any concrete symbol/service named in the question — jsat__get_function /
jsat__get_class / jsat__trace_call_chain directly (these are graph lookups, not
AI calls). Synthesize the answer yourself from that raw data in Phase 6, and say
plainly that the AI-backed answer could not be generated.
If the primary tool is one of the non-AI tools (trace_call_chain, get_function/
get_class, get_test_gaps) and IT independently errors, that is a normal tool
failure, not AI-unavailability — report the error, do not claim degraded mode.
Label: "💬 Phase 3/6 — Execute (<tool>)"

### Phase 4 — Execute (Secondary) (~15s)
If a second relevant service was identified in Phase 2:
  Call same primary tool on second service, or jsat__query(service=<second>)
  Label: "💬 Phase 4/6 — Secondary (<service>)"
Else:
  Call: jsat__query(question=<optimized_prompt>) with no service scope
  Label: "💬 Phase 4/6 — Broader Context"

### Phase 5 — Verify (~5s)
Scan Phase 3-4 answers for 2-3 concrete claims to spot-check against the graph:
  function/method name → jsat__get_function(name=<fn>)
  class name           → jsat__get_class(name=<cls>)
  service name         → already known from Phase 2 (no extra call needed)

Mark each claim:
  Found in graph   → ✅ verified
  Not found        → ⚠️ unverified (may be inferred or not yet indexed)

If Phase 3-4 produced no checkable claims (or both timed out):
  Fall back: jsat__short(question=<optimized_prompt>) — but ONLY if DEGRADED is
  not already set from Phase 3/4. jsat__short is itself AI-backed (a terse
  jsat__query variant), so if the provider is already known to be down this call
  will just repeat the failure. If DEGRADED is set, skip this fallback entirely
  and mark Phase 5 as "skipped — AI backend unavailable".
Label: "🔍 Phase 5/6 — Verify"

### Phase 6 — Synthesize (by you, Claude — no tool call)
- If DEGRADED was set in any earlier phase, lead with that: state plainly that
  the AI backend (jsat__query/rewrite/investigate_incident/short) was
  unavailable, name which phase hit it, and that the following answer is built
  from raw graph data + your own reasoning, not from the AI-optimized tool
  chain — do not present it as a normal, fully-verified answer.
- Lead with the direct answer to the original question
- Present ✅ verified facts first, clearly attributed
- Flag ⚠️ unverified claims: "Note: <X> was not found in the index — treat as inferred"
- Add supporting detail from Phases 3-4
- Note conflicts or gaps between phases
Label: "✅ Phase 6/6 — Final Answer"

## Phase splits for --phases N
N=2: [discuss+optimize] / [execute + verify + synthesis]
N=3: [discuss+optimize] / [scope + execute] / [verify + synthesis]
N=4: [discuss+optimize] / [scope] / [execute] / [verify + synthesis]
N=6: full pipeline above (default)

After each phase completes, update session file: mark phase [x] with 1-sentence finding.
After Phase 6: set status → completed. Print: "✅ Session complete: <path>"
(If interrupted, run /jsat prompt --continue to resume from the last incomplete phase.)

## Actions File

From Phase 6 synthesis, extract concrete follow-up work:
  - Fixes for ⚠️ unverified claims (look them up and correct the answer)
  - Decisions to log (run /jsat decide log)
  - Knowledge to store (run /jsat knowledge-add)
  - Tests or verification steps recommended

Write ~/.jsat/sessions/prompt-actions-<SLUG>-<YYYYMMDD-HHMM>.md.
Print: "📋 Actions: <path>"

Execute each "- [ ]" action in sequence. Mark [x] as done.
When all done: status → completed. Print: "✅ All actions complete: <path>"

## --single Flag
If --single: classify → optimize → jsat__query(question=<optimized_prompt>) once.
No verification in single mode. If the result is "[AI unavailable...": report
that plainly — there is no fallback in single-shot mode by design (that's the
tradeoff for speed); suggest dropping --single so Phase 3 can use the non-AI
degraded path instead.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
