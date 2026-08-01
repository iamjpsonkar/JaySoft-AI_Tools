---
description: Trace downstream impact of a change. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right blast-radius tool:

Supported flags:
  --file           → call jsat__blast_radius_file with path=<rest>
  --diff           → call jsat__blast_radius_diff with diff=<rest>
  --symbol         → call jsat__blast_radius_symbol with symbol=<rest>
  --severity <lvl> → filter output to breaking|degraded|warning|safe only
  (no flag)        → call jsat__blast_radius with target=<rest>

Examples:
  /jsat-blast-radius src/payment/service.py
    → jsat__blast_radius(target="src/payment/service.py")

  /jsat-blast-radius --file src/payment/service.py
    → jsat__blast_radius_file(path="src/payment/service.py")

  /jsat-blast-radius --symbol PaymentService.process
    → jsat__blast_radius_symbol(symbol="PaymentService.process")

  /jsat-blast-radius --severity breaking src/payment/service.py
    → jsat__blast_radius(target="src/payment/service.py", severity_filter=["breaking"])

Group results by severity: breaking / degraded / warning / safe.
Show summary counts first. Show Mermaid diagram if impacts > 5.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
