---
description: Multi-model code review. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right review tool:

Supported flags:
  --findings        → call jsat__get_review_findings to show results of last review
  --bugs            → call jsat__get_high_confidence_bugs to list confirmed bugs only
  --min high        → filter to high-confidence findings only
  --min medium      → filter to medium+ (default)
  (no flag)         → call jsat__submit_for_review with diff=<rest>

Examples:
  /jsat-review <paste diff here>
    → jsat__submit_for_review(diff="<diff>")

  /jsat-review --findings
    → jsat__get_review_findings()

  /jsat-review --bugs
    → jsat__get_high_confidence_bugs()

Show findings grouped by confidence: high → medium → low.
Highlight bugs confirmed by 2+ models.

LARGE DIFF STRATEGY: For diffs >500 lines, split by file and review in chunks:
  /jsat-review <first file's diff>   then   /jsat-review <next file's diff>
Then run /jsat-review --bugs to see cross-chunk high-confidence findings.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
