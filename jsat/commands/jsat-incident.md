---
description: Investigate a production incident. Supports subcommands in $ARGUMENTS.
---

Parse $ARGUMENTS for an optional subcommand, then call the right tool:

Subcommands:
  hypotheses          → call jsat__get_hypotheses to list ranked root-cause hypotheses
  recent [path]       → call jsat__get_recent_changes to show recent commits in area
  runbook <svc>       → delegate to jsat-runbook.md's full behavior. Read the file
                        at jsat/commands/jsat-runbook.md now (Read tool, exact path
                        relative to the JSAT repo root) and follow it verbatim for
                        this invocation — do not reimplement a subset of it here.
                        Concretely, that means: (1) pass everything after `runbook`
                        as jsat-runbook's own $ARGUMENTS, so `runbook sections <svc>`
                        correctly routes to the outline-only mode instead of always
                        calling the full generator; (2) run its pre-check —
                        jsat__list_services() to confirm <svc> resolves to a real
                        indexed service before generating anything; (3) on
                        "[AI unavailable...]" from jsat__generate_runbook, use its
                        documented raw-graph fallback (trace_call_chain,
                        blast_radius, list_services, get_consumers, list_endpoints)
                        and the same "⚠ AI unavailable — assembled runbook..." label
                        — never fall back to a plain jsat__generate_runbook(target=X)
                        call with no validation and no degraded-mode handling, since
                        that reintroduces exactly the duplication this delegation
                        exists to avoid.
  (no subcommand)     → call jsat__investigate_incident with description=<rest>

If no subcommand matched AND the remaining text is empty (e.g. bare `/jsat-incident`
with nothing else): stop and ask the user for an incident description — do not
call jsat__investigate_incident(description="") and let it score commits against
nothing meaningful.

jsat__investigate_incident itself is pure heuristic git-commit scoring (recency,
blast-radius weight, frequency, pattern match) — it does NOT call an LLM, so it
has no "[AI unavailable]" failure mode.

Supported flags:
  --since <time>      → limit commit search to window (24h, 7d)
  --service <name>    → scope graph correlation to one service

Examples:
  /jsat-incident 500 errors spiking on checkout since 14:00
    → jsat__investigate_incident(description="500 errors spiking on checkout since 14:00")

  /jsat-incident hypotheses
    → jsat__get_hypotheses()  (after a previous investigation)

  /jsat-incident recent src/payment/
    → jsat__get_recent_changes(target="src/payment/")

  /jsat-incident runbook PaymentService
    → follow jsat-runbook.md's full flow: confirm "PaymentService" resolves via
      jsat__list_services() first, THEN jsat__generate_runbook(target="PaymentService")
      (or its AI-unavailable raw-graph fallback if that call degrades) — not a bare
      unvalidated tool call

  /jsat-incident runbook sections PaymentService
    → follow jsat-runbook.md's `sections` mode: outline only, no full content

Show top hypotheses ranked by score. For each: commit hash, author, changed files, keyword evidence.
BUDGET STRATEGY: Use --since 24h to narrow the commit range on large repos.
  Override budget: /jsat incident timeout=120 <description>
  ⏱ progress notification = still running (wait or skip). ⛔ _hard_timeout = retry with narrower --since window.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
