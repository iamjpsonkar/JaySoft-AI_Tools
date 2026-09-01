---
description: Answer a question about this codebase using JSAT's graph index. Supports service scoping.
---

Parse $ARGUMENTS for optional flags, then call jsat__query:

Supported flags:
  --service <name>  → scope answer to one service (reduces context, avoids timeout)
  --short           → prepend brevity constraint (≤3 sentences)
  (no flag)         → full graph query

--service SCOPE SEMANTICS (unverified against tool internals — flag this
uncertainty rather than assuming): this command file does not know, and cannot
promise, whether jsat__query(service=<name>) hard-filters the graph to that
service's nodes/edges only, or uses it as a soft ranking hint while still
allowed to pull in cross-service context when directly relevant (e.g. an
external call from PaymentService into OrderService). Other command files
(e.g. /jsat-prompt's --service, /jsat-plan) call jsat__query with service
scoping and implicitly assume results are correctly narrowed — do not
propagate that assumption as fact. If a scoped answer looks suspiciously thin,
declines to address part of the question, or contradicts something you know
spans multiple services, say so and suggest re-running unscoped to check
whether the scope silently dropped relevant cross-service context — do not
treat a scoped answer as strictly more precise than an unscoped one without
that check.

Examples:
  /jsat-query what does the payment service do?
    → jsat__query(question="what does the payment service do?")

  /jsat-query --service PaymentService how is retry handled?
    → jsat__query(question="how is retry handled?", service="PaymentService")

BUDGET HANDLING: jsat__query has a soft time budget (notification-only — call keeps running).
  Override: /jsat query timeout=120 what does checkout do?  → soft budget 120s
  ⏱ progress notification while running: query is still running, AI can wait or decide to skip
  ⏱ _slow in response: completed after budget — result is valid, consider scoping next time
  ⛔ _hard_timeout in response: force-killed at 5× budget — must retry with narrower scope
  Recovery steps (SLOW/TIMEOUT — the query eventually ran, just took too long):
    1. Narrow scope: add --service <name> to limit context
    2. Use /jsat-short for a briefer answer (≤3 sentences)
    3. Break complex questions into smaller focused queries

AI-UNAVAILABLE HANDLING (a DIFFERENT failure mode from slow/timeout above — do
not treat it the same way): jsat__query requires a live LLM provider (e.g.
Ollama) to synthesize an answer over the graph. When that provider is down, the
tool returns instantly with a response that IS or STARTS WITH "[AI unavailable"
— this is not a timeout, retrying with --service or /jsat-short will NOT help
because /jsat-short calls the same AI-backed query path and will fail
identically. Do not apply the timeout recovery steps above to this case.
  Recovery steps (AI UNAVAILABLE):
    1. Say so plainly: report that the AI backend is down, not that the answer
       was empty or that the question was bad.
    2. Do not retry jsat__query or jsat__short — same dependency, same result.
    3. If the question names a specific symbol/service, answer what you can
       from the non-AI graph tools instead: jsat__get_function, jsat__get_class,
       jsat__trace_call_chain, jsat__list_services, jsat__get_index_status —
       these do not require the LLM provider — then reason over that raw data
       yourself (you are already an LLM) and clearly label the result as a
       "graph-only answer, AI synthesis unavailable".
    4. Suggest the user check the AI provider (e.g. is Ollama running/reachable)
       before retrying jsat__query itself.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
