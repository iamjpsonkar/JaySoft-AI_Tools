---
description: Check how much of a model's context window a text uses. Supports --model flag.
---

Parse $ARGUMENTS for optional --model flag:

  --model <name>   → use specified model for limit calculation
  (no flag)        → use current session model (claude-sonnet-4-6[1m] or as configured)

Known model context limits:
  claude-sonnet-4-6[1m]  → 1,048,576 tokens
  claude-sonnet-4-6       → 200,000 tokens
  claude-haiku-4-5        → 200,000 tokens
  gpt-4o                  → 128,000 tokens
  gpt-4o-mini             → 128,000 tokens

Use jsat__token_budget with text=<stripped text> and model=<name>.
Show: tokens used, limit, percentage, headroom, status (ok / warn / critical).
Warn at ≥80%. Flag critical at ≥95%.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
