---
description: Find untested code paths and optionally generate tests. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right test tool:

Supported flags:
  --generate         → after finding gaps, call jsat__generate_unit_test for each gap
  --integration      → call jsat__generate_integration_test instead of unit tests
  --contract <A> <B> → call jsat__generate_contract_test between two services
  --untested         → call jsat__list_untested_paths for a flat list
  --service <name>   → scope to one service (avoids timeout on large codebases)
  (no flag)          → call jsat__get_test_gaps with path=<rest or ".">

Examples:
  /jsat-test-gaps src/payment/
    → jsat__get_test_gaps(path="src/payment/")

  /jsat-test-gaps --generate src/payment/
    → jsat__get_test_gaps then jsat__generate_unit_test for each gap

  /jsat-test-gaps --untested
    → jsat__list_untested_paths()

  /jsat-test-gaps --contract PaymentService RefundService
    → jsat__generate_contract_test(producer="PaymentService", consumer="RefundService")

LARGE CODEBASE STRATEGY: Run per-service to stay within budget:
  /jsat-test-gaps --service PaymentService   then   /jsat-test-gaps --service RefundService
  Override budget: /jsat test-gaps timeout=120 src/payment/
  ⏱ progress notification = still running (wait or skip). ⛔ _hard_timeout = retry scoped.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
