---
description: Pre-implementation planning — six forcing questions + scope/architecture/security review before writing code.
---

Pre-implementation planning gate. Before writing any code, surface assumptions, scope risks, and architectural concerns.

Parse $ARGUMENTS for optional flags:
  --scope          → scope review only: what to build and why
  --architecture   → architecture review: how to build it
  --security       → security review: what can go wrong
  --full           → run all three perspectives (default)
  (no flag)        → full three-perspective review

## Six Forcing Questions (always run first)

Before any perspective review, answer these six questions from the task description and graph context:
  1. What is the exact problem being solved?
  2. Who experiences this problem and how often?
  3. What is the cost of NOT solving it?
  4. What already exists in the codebase that partially handles this?
  5. What is the minimum change that would solve it?
  6. What is the hardest part — and what assumption am I making about it?

Call: jsat__ithinking_audit_assumptions(subtask=<task>) — NOT task=<task>; this
tool's parameter is named "subtask" (verified against the MCP schema in
/jsat-ithinking's docs), and calling it with "task" will fail schema validation.
Call: jsat__query(question="what exists in the codebase related to: <task>") to answer question 4.

Note on overlap with /jsat ithinking: this command's forcing-question audit and
jsat__ithinking_plan's own Phase 4 both call jsat__ithinking_audit_assumptions
under the hood. If the user already ran (or is about to run) /jsat ithinking
plan on this same task in this session, do not call the audit tool a second
time here — reuse that Phase 4 output instead and note that question 4/6's
assumption check was answered from the earlier ithinking-plan call, not a
fresh one. Only invoke the audit call above when no such plan has run yet.

FALLBACK if jsat__query returns "[AI unavailable]" (a down/unconfigured AI provider
takes the whole tool with it — this is a common failure mode, not rare): fall back to
Bash (`grep -ril` for the task's key nouns/identifiers across the repo) to find
candidate existing files, then call jsat__get_function / jsat__get_class on any hits
to describe what they actually do — those two tools are pure graph lookups and do not
need the AI backend. Mark question 4's answer as "Bash-enumerated" in the output so
the user knows it wasn't a semantic search.

Label: "🔍 Forcing Questions"

## Scope Perspective (--scope or --full)
Classify the task: full scope / reduced scope (cut what loses no core value) / expanded scope (what adjacent improvement would compound value?).
If Q4 identified an existing file/symbol this task would extend: call
jsat__blast_radius(target=<that file or symbol>). If Q4 found nothing (this is
genuinely new code with no existing integration point), skip the call and state
"new code path — no existing blast radius to measure" instead of calling
blast_radius with an empty/guessed target.
Show: recommended scope with reason. Label: "📐 Scope"

## Architecture Perspective (--architecture or --full)
Evaluate the implementation approach:
  - What existing patterns should this follow? (from graph context)
  - What data flows are affected? (from blast-radius above)
  - What are the 2 most likely failure modes?
  - One-line flow: input → transformation → output
Label: "🏗 Architecture"

## Security Perspective (--security or --full)
Flag risks before implementation:
  - What user inputs reach this code path?
  - What external calls or side effects are involved?
  - What is the blast radius if this function behaves unexpectedly?
Call: jsat__get_auth_coverage() if auth is relevant.
Label: "🔒 Security"

## Output
Print a one-page planning brief:
  Decision: build as described / reduce scope / defer / delegate
  Architecture: <one-line approach>
  Top risk: <one-line>
  First step: <specific file or function to change first>


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
