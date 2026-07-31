---
description: Generate an incident runbook for a service or component.
---

Parse $ARGUMENTS for optional subcommands, then call jsat__generate_runbook:

  sections <target>   → show section outline only (no full content)
  (no subcommand)     → full runbook for target=<rest>

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

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
