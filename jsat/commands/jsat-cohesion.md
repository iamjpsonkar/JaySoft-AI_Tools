---
description: File and function cohesion analysis — flags oversized files, high complexity, and mixed responsibilities.
---

Analyze the codebase for cohesion problems: oversized files, high-complexity functions, and mixed responsibilities.

Parse $ARGUMENTS for optional flags:
  --service <name>    → scope to one service
  --threshold <N>     → flag files with more than N lines (default: 800)
  --functions         → show function-level analysis only (no file-level)
  (no flag)           → full cohesion report for path=<rest or ".">

## What it checks

Files:
  - Lines > 800 (default threshold) → likely need extraction
  - Multiple unrelated responsibilities → split into focused modules

Functions:
  - Cyclomatic complexity > 10 → likely needs simplification
  - Lines > 150 → likely doing too much
  - High outgoing edges in blast-radius (calls many unrelated things)

## How it works

Call: jsat__get_index_status() for graph overview
Call: jsat__query(question="which files are largest and most complex in the codebase?")
Call: jsat__get_test_gaps(path=<path>) to correlate complexity with test coverage gaps

For the top findings, cross-reference with blast-radius to identify which large files
have the highest downstream impact (most urgent to refactor).

## Output format

📊 **Cohesion Report**

  🔴 HIGH priority (extract or split):
    <file> — <N> lines, complexity <X> — suggest extracting: <function names>

  🟡 MEDIUM priority (schedule refactor):
    <file> — <N> lines, complexity <X>

  ✅ Healthy: <N> files within thresholds

  Top recommendation: <one specific first action — most impactful>

TIMEOUT STRATEGY: For large repos, scope with --service <name> to avoid timeout.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
