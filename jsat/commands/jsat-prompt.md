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

The query is every word that is NOT a flag. Strip all flags; join the rest.
Priority when multiple optimizer flags: --agents beats --rewrite.

## Phased Mode (default, --phases 6)

Run in 6 sequential phases. Show output after each.

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
Read `optimized_prompt`. Save for all subsequent phases.
Show: optimized prompt, tokens before→after.
If --diff: also call jsat__prompt_diff and show diff.
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
If tool returns "[AI unavailable]": fall back to jsat__query.
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
  Fall back: jsat__short(question=<optimized_prompt>)
Label: "🔍 Phase 5/6 — Verify"

### Phase 6 — Synthesize (by you, Claude — no tool call)
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

## --single Flag
If --single: classify → optimize → jsat__query(question=<optimized_prompt>) once.
No verification in single mode.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
