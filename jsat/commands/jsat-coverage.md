---
description: Show behavioral test coverage estimate. Supports generating tests for gaps.
---

Parse $ARGUMENTS for optional flags, then call jsat__get_behavioral_coverage:

Supported flags:
  --generate       → after showing gaps, call jsat__generate_unit_test for top uncovered paths
  --service <name> → scope to one service (avoids timeout on large codebases)
  --limit N        → show only top N uncovered paths (default: all)
  (no flag)        → full coverage report for path=<rest or ".">

Examples:
  /jsat-coverage src/payment/
    → jsat__get_behavioral_coverage(path="src/payment/")

  /jsat-coverage --generate --limit 5 src/payment/
    → coverage report + generate tests for 5 most critical uncovered paths

  /jsat-coverage --service PaymentService
    → scope to one service to stay within soft budget

Show: overall % covered, uncovered functions, over-mocked tests, endpoint gaps.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
