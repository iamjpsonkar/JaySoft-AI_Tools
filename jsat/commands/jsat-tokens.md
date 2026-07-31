---
description: Count, compress, or check token budget. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right token tool:

Supported flags:
  --compress           → call jsat__token_compress with text=<rest>  (apply compression)
  --model <name>       → call jsat__token_budget with text=<rest>, model=<name>
  --budget <model>     → same as --model  (alias)
  (no flag)            → call jsat__token_count with text=<rest>

Examples:
  /jsat-tokens explain the payment service
    → jsat__token_count(text="explain the payment service")

  /jsat-tokens --compress <paste large context here>
    → jsat__token_compress(text="<text>")  → show savings and compressed output

  /jsat-tokens --model gpt-4o <paste context here>
    → jsat__token_budget(text="<text>", model="gpt-4o")  → show % used, headroom, status

  /jsat-tokens --model claude-sonnet-4-6 <paste context>
    → jsat__token_budget(text="<text>", model="claude-sonnet-4-6")

Show: token count, savings (if compressed), budget % used and status (ok/warn/critical).

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
