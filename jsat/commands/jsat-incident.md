---
description: Investigate a production incident. Supports subcommands in $ARGUMENTS.
---

Parse $ARGUMENTS for an optional subcommand, then call the right tool:

Subcommands:
  hypotheses          → call jsat__get_hypotheses to list ranked root-cause hypotheses
  recent [path]       → call jsat__get_recent_changes to show recent commits in area
  runbook <svc>       → call jsat__generate_runbook to produce an incident runbook
  (no subcommand)     → call jsat__investigate_incident with description=<rest>

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
    → jsat__generate_runbook(target="PaymentService")

Show top hypotheses ranked by score. For each: commit hash, author, changed files, keyword evidence.
TIMEOUT STRATEGY: Use --since 24h to narrow the commit range on large repos.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
