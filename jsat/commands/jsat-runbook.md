---
description: Generate an incident runbook for a service or component.
---

Parse $ARGUMENTS for optional subcommands, then call jsat__generate_runbook:

  sections <target>   → show section outline only (no full content)
  (no subcommand)     → full runbook for target=<rest>

If $ARGUMENTS is empty after stripping BUDGET flags (no target given at all,
including "sections" with nothing after it): stop and ask for a target — do not
call jsat__generate_runbook(target="") and let it guess.

Before generating, call jsat__list_services() and confirm <target> matches an
indexed service (or is a known component/file jsat__get_function /
jsat__get_class can resolve). If it doesn't match anything, suggest the closest
name and stop — a runbook generated for a target that doesn't exist in the graph
will fabricate plausible-sounding but ungrounded content instead of erroring.

Examples:
  /jsat-runbook PaymentService
    → jsat__generate_runbook(target="PaymentService")

  /jsat-runbook sections PaymentService
    → outline only: symptoms, diagnosis, rollback, escalation, monitoring

Full runbook includes:
  1. Symptoms and alert signatures
  2. Diagnosis steps (with graph-derived call chain)
  3. Rollback procedure
  4. Escalation path and contacts
  5. Prevention and monitoring checklist

jsat__generate_runbook synthesizes prose from the graph and, like jsat__query,
needs a working LLM backend — expect the same "[AI unavailable: ..." failure
mode when the provider is down (confirmed common, not rare). If it fails that
way, do not fabricate a runbook from memory. Fall back to assembling the raw
material yourself from AI-free tools and present it as a rougher, unpolished
runbook rather than silently degrading quality:
  - Symptoms/diagnosis → jsat__trace_call_chain(symbol=<target's entry point>)
  - Blast radius / what breaks → jsat__blast_radius(target=<target>)
  - Escalation / ownership → jsat__list_services() metadata for <target>, plus
    jsat__get_consumers(target=<target>) for who else depends on it
  - Monitoring checklist → jsat__list_endpoints(service=<target>) for surfaces
    that should have alerts
Label this path explicitly: "⚠ AI unavailable — assembled runbook from raw graph
data, not narrative-generated. Verify before treating as authoritative."


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
