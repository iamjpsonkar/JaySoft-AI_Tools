---
description: Ask any question — get the briefest possible correct answer (≤3 sentences).
---

Parse $ARGUMENTS for optional --one-line flag:

  --one-line  → request exactly one sentence
  (no flag)   → ≤3 sentences

Use jsat__short with question=<stripped arguments> (or jsat__query if jsat__short unavailable),
prepending the brevity constraint: "Answer in ≤3 sentences, plain language. No preamble."

Show only the AI response — no framing, no metadata.
Use as a fast fallback when /jsat-query times out.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
