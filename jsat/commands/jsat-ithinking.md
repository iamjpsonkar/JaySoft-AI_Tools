---
description: IThinking meta-cognitive reasoning. Supports subcommands in $ARGUMENTS.
---

Parse $ARGUMENTS for an optional subcommand, then call the right IThinking tool:

Subcommands:
  plan <task>      → call jsat__ithinking_plan with task=<task>  (phases 0-4, default)
  reflect <done>   → call jsat__ithinking_reflect with subtask=<done>  (phase 6 log)
  audit <task>     → call jsat__ithinking_audit_assumptions with task=<task>
  execute <plan>   → call jsat__ithinking_execute with subtask=<plan>
  estimate <task>  → call jsat__ithinking_token_estimate with task=<task>
  (no subcommand)  → call jsat__ithinking_plan with task=<rest>  (same as plan)

Examples:
  /jsat-ithinking refactor the payment retry logic
    → jsat__ithinking_plan(task="refactor the payment retry logic")

  /jsat-ithinking plan add rate limiting to the checkout API
    → jsat__ithinking_plan(task="add rate limiting to the checkout API")

  /jsat-ithinking reflect completed refactor of PaymentService.process()
    → jsat__ithinking_reflect(subtask="completed refactor of PaymentService.process()")

  /jsat-ithinking audit migrate users table to add nullable column
    → jsat__ithinking_audit_assumptions(task="migrate users table to add nullable column")

  /jsat-ithinking estimate write comprehensive tests for the checkout flow
    → jsat__ithinking_token_estimate(task="write comprehensive tests for the checkout flow")

Display plan clearly. After the user approves, proceed. Then reflect on what was done.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
