---
description: Find untested code paths and optionally generate tests. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right test tool:

Supported flags:
  --generate         → after finding gaps, call jsat__generate_unit_test for each gap
  --integration      → call jsat__generate_integration_test instead of unit tests
  --contract <A> <B> → call jsat__generate_contract_test between two services;
                        <A> is ALWAYS the producer, <B> is ALWAYS the consumer
                        (this matches the tool's required `producer`/`consumer`
                        schema fields — order matters, it is not symmetric)
  --untested         → call jsat__list_untested_paths for a flat list
  --service <name>   → scope to one service (avoids timeout on large codebases)
  (no flag)          → call jsat__get_test_gaps with path=<rest or ".">

IMPORTANT — what --generate/--integration/--contract actually return: these
tools do NOT generate test code. Each one returns
`{"status": "delegated", "suggested_query": "<prompt>"}` — a suggested prompt,
nothing more. Do not present that JSON as the finished test, and do not
mechanically forward `suggested_query` to jsat__query to get the code — that
just adds a second AI call for no benefit and fails outright whenever the AI
provider is down ("[AI unavailable: ...]"), per jsat-status.md. Since you (the
assistant) can already write code, use the `suggested_query` text plus
jsat__get_function / jsat__get_class / jsat__get_test_gaps context on the
target directly and write the real test yourself in this response.

VERIFY WHAT YOU WROTE, DON'T JUST HAND IT OVER: writing the test file is not
the end of the task — a suggestion followed by hand-written code with no
check afterward can silently produce a file that doesn't parse, imports the
wrong module path, or never actually runs (e.g. a typo'd test function name
the runner won't collect). After writing each test file:
  1. Confirm the file actually exists on disk at the path you intended
     (Read it back, or `ls` it) — do not assume the write succeeded.
  2. Run it (the repo's test runner — pytest/jest/go test/etc., whichever
     this project uses) and report the real pass/fail result, not just
     "test written". If it fails, that is still useful output — say so and
     show the failure, don't suppress it to make the gap look closed.
  3. If there is no test runner available or running it is out of scope for
     this invocation, say explicitly "written but not executed — verify
     manually" rather than implying it was confirmed working.
Do not report a test gap as filled on the strength of the suggestion alone.

Examples:
  /jsat-test-gaps src/payment/
    → jsat__get_test_gaps(path="src/payment/")

  /jsat-test-gaps --generate src/payment/
    → jsat__get_test_gaps, then for each gap call jsat__generate_unit_test to
      get a suggested_query, then write the actual test yourself using that
      prompt + graph context (see note above — do not just echo the JSON)

  /jsat-test-gaps --untested
    → jsat__list_untested_paths()

  /jsat-test-gaps --contract PaymentService RefundService
    → jsat__generate_contract_test(producer="PaymentService", consumer="RefundService")
      (PaymentService is the producer, RefundService is the consumer — swapping
      the two changes the contract's meaning, not just its label)

LARGE CODEBASE STRATEGY: Run per-service to stay within budget:
  /jsat-test-gaps --service PaymentService   then   /jsat-test-gaps --service RefundService
  Override budget: /jsat test-gaps timeout=120 src/payment/
  ⏱ progress notification = still running (wait or skip). ⛔ _hard_timeout = retry scoped.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
