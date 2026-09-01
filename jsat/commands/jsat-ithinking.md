---
description: IThinking meta-cognitive reasoning. Supports subcommands in $ARGUMENTS.
---

Parse $ARGUMENTS for an optional subcommand, then call the right IThinking tool:

Subcommands:
  plan <task>      → call jsat__ithinking_plan with task=<task>  (phases 0-4, default)
  reflect <done>   → call jsat__ithinking_reflect with task=<original task text>,
                     result=<summary of what actually happened>  (phase 6 log)
  audit <task>     → call jsat__ithinking_audit_assumptions with subtask=<task>
  execute <plan>   → call jsat__ithinking_execute with task=<plan>
  estimate <task>  → call jsat__ithinking_token_estimate with task=<task>
  (no subcommand)  → call jsat__ithinking_plan with task=<rest>  (same as plan)

PARAMETER NAMES ARE NOT INTERCHANGEABLE — verified against the MCP tool schemas:
  ithinking_plan             requires: task
  ithinking_execute          requires: task        (NOT "subtask" — a common mistake
                                                      since the CLI subcommand is
                                                      literally named "execute <plan>")
  ithinking_reflect          requires: task AND result — BOTH are mandatory. There is
                                                      no "subtask" parameter for this
                                                      tool at all; calling it with only
                                                      one string will fail schema
                                                      validation. Track the original
                                                      task text from the plan/execute
                                                      step earlier in the conversation
                                                      and pass it as `task`; pass the
                                                      outcome description as `result`.
  ithinking_token_estimate   requires: task
  ithinking_audit_assumptions requires: subtask     (NOT "task" — this is the one
                                                      tool in this family that uses
                                                      "subtask", not "task")

## Reading jsat__ithinking_plan's output — this was previously undocumented and
had to be inferred ad hoc; document it explicitly so it isn't re-inferred wrong

The plan call returns 5 phases. Each has a concrete meaning and a concrete thing
to DO with it — this is not narrative filler to skim past:

  Phase 0 — Intent: flags ambiguity in the task wording. If it prints
    "[!] Phase 0: Intent — Ambiguity detected in: '<task>'", that is a real
    signal, not decoration: the tool could not confidently parse a single clear
    intent from the wording. Do not proceed as if the task were unambiguous —
    either ask the user to disambiguate, or state explicitly which interpretation
    you're proceeding under and why, so a wrong guess is visible and correctable.

  Phase 1 — Local Feasibility / Route: this is the single most consequential
    field in the whole response and controls what you do next:
      Route: [LOCAL] Graph query (0 tokens) → the task can be answered from the
        graph/tool data alone, no LLM reasoning required beyond what a jsat__*
        tool call already returns. Proceed to call the graph-native tool the
        task implies (query, blast_radius, get_function, etc.) and answer from
        its output directly.
      Route: [LLM] AI reasoning required → the task needs YOU (the assistant
        reading this) to actually reason about it — the graph alone cannot
        produce the answer. This does NOT mean "call another jsat__* AI tool
        and let it reason instead" (if that tool's own AI backend is also down,
        you've gained nothing) — it means synthesize the answer yourself, using
        whatever graph data you can gather as raw material. This exact
        situation occurred live this session: a plan call routed to "[LLM] AI
        reasoning required" for a request to critique and rewrite a command
        file, and the correct response was for the assistant itself to read the
        file and produce the critique — not to call a second AI-backed tool and
        hope it worked.
    If jsat__ithinking_plan's own phase-1 routing decision seems wrong for the
    task (e.g. it routes [LOCAL] for something that clearly needs judgment, or
    [LLM] for a plain graph lookup), say so and route yourself rather than
    following it blindly — Phase 1 is itself a heuristic, not a guarantee.

  Phase 2 — Prompt Optimised: an offline-rewritten version of the task text
    (filler removed, structure normalized). Use this as the actual task text
    fed into whatever you do next (Phase 1's routed action) instead of the
    user's raw wording — it is specifically prepared to be reasoned over, and
    ignoring it in favor of the original wording throws away that preparation.

  Phase 3 — Task Decomposition: a numbered breakdown of the task into subtasks.
    Use this as your execution checklist if you proceed to actually do the work
    — do not silently re-derive your own breakdown when one was already produced.

  Phase 4 — Assumption Audit: flagged assumptions (e.g. "[all] Assumes all
    instances — verify scope"). Treat each flagged assumption as a thing to
    either verify before proceeding or state as an explicit caveat in your
    final answer — do not silently accept a flagged assumption as settled fact.

  plan <task>: after showing all 5 phases, ask the user for confirmation before
    proceeding. "Proceeding" means: once confirmed, YOU (the assistant) carry
    out the original task yourself, using Phase 3's decomposition as your
    checklist and Phase 4's assumption audit as things to double-check along
    the way, guided by Phase 1's routing decision for HOW to carry it out. This
    is NOT the same as calling jsat__ithinking_execute (see below — a separate
    tool with its own gated-execution/hard-stop contract). If Phase 4 flags a
    hard-stop-worthy destructive operation (drop table, rm -rf, truncate, force
    push, etc.), treat that as a stop-and-confirm signal before doing anything
    irreversible, same as ithinking_execute's own gate would.

## `audit` vs `plan`'s built-in Phase 4 — when to use which

`plan` ALREADY runs an assumption audit as its Phase 4 — running the full 5-phase
plan and then separately running `audit` on the same task is redundant, not
additive. Use standalone `audit <task>` only when you specifically want JUST the
assumption check, without the overhead of intent-classification, routing, prompt
optimization, and decomposition that full `plan` also produces — e.g. a quick
sanity check on a task you already understand and have already decomposed
yourself, where you just want a second pass for hidden assumptions before acting.
If you're about to run `plan` anyway, don't also run `audit` first — you'll get
the same assumption-audit content twice.

## `execute <plan>` — the gated-execution contract

jsat__ithinking_execute is phases 5-6 of the IThinking pipeline (plan's phases
0-4 hand off into execute's phases 5-6 when the two are chained: plan produces
the decomposition and assumption audit, execute is what actually walks through
them with gating). Its "gated" behavior means: before each decomposed subtask
from Phase 3, it re-checks that subtask against the Phase 4 assumption audit and
against any hard-stop patterns (irreversible/destructive operations). Concretely:
  - If a subtask is clear to proceed: it executes (or, since this is a prompt-
    driven tool without direct system access, it returns guidance for YOU to
    execute that subtask) and moves to the next.
  - If a subtask trips a hard-stop condition: it returns a stop signal instead of
    proceeding — treat this exactly like Phase 4's own hard-stop flag under
    `plan`: do not push past it without explicit user confirmation.
  - Use `execute` (rather than just doing the task yourself after `plan`
    confirms) when you specifically want each decomposed subtask individually
    gated as you go, rather than doing the whole task in one pass yourself after
    a single up-front confirmation. For most tasks, `plan` followed by doing the
    work yourself (as `plan`'s own instructions above describe) is sufficient
    and faster; reach for `execute` when the task has multiple genuinely
    separable, individually-risky steps where you want a gate between each one,
    not just one gate at the start.

## `estimate <task>` — what to do with the result

jsat__ithinking_token_estimate returns a token/complexity estimate for the task.
This number is only useful if you act on it:
  - If the estimate is large relative to the current session's remaining context
    (cross-check with jsat__token_budget or jsat__tokens --model if you need the
    session's actual headroom), say so explicitly and suggest splitting the task
    into smaller pieces BEFORE starting, rather than discovering the overrun
    mid-task.
  - If the estimate is small, proceed normally — there's nothing further to do
    with a "this is cheap" result beyond noting it.
  - Do not just print the raw number and stop — the point of estimating before
    starting is to change what you do next (split vs proceed), not to report a
    number for its own sake.

Examples:
  /jsat-ithinking refactor the payment retry logic
    → jsat__ithinking_plan(task="refactor the payment retry logic")

  /jsat-ithinking plan add rate limiting to the checkout API
    → jsat__ithinking_plan(task="add rate limiting to the checkout API")

  /jsat-ithinking reflect completed refactor of PaymentService.process()
    → jsat__ithinking_reflect(task="refactor PaymentService.process() retry logic",
                               result="completed refactor of PaymentService.process()")
    If <done> is empty/whitespace: do NOT call the tool with an empty result — a
    reflection needs a concrete "what did I just do" to be useful. Ask the user
    what to reflect on instead of guessing. This phase normally follows a
    plan/execute call earlier in the same session; if none happened, it will
    still log what you pass it, but tell the user this is a standalone
    reflection (not linked to a tracked plan) so they know it won't show up
    when they later look up that plan's history. After the call, confirm what
    was logged (outcome, what worked/didn't, follow-ups) rather than echoing a
    raw success flag.

  /jsat-ithinking audit migrate users table to add nullable column
    → jsat__ithinking_audit_assumptions(subtask="migrate users table to add nullable column")

  /jsat-ithinking estimate write comprehensive tests for the checkout flow
    → jsat__ithinking_token_estimate(task="write comprehensive tests for the checkout flow")

Display plan clearly. After the user approves, proceed. Then reflect on what was done,
keeping the original task text on hand so the reflect call can supply both required
parameters.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
