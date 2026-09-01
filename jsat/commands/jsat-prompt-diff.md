---
description: Show what you typed vs what JSAT sent to the AI after optimization.
---

Use jsat__prompt_diff with query="$ARGUMENTS" to show the before/after comparison: raw input vs fully optimized prompt with injected context, constraints, few-shot examples, and model formatting. Label one panel 'You sent' and the other 'AI received'.

AI-BACKEND CAUTION: if the "AI received" side of the result is or contains
"[AI unavailable...", the optimization step itself failed — do not display it
as if it were a normal optimized prompt (that would misrepresent a failure as a
successful diff with an empty/garbage right panel). Instead:
  1. Call jsat__prompt_optimize (offline, non-AI) with the same query as a
     substitute and clearly label that panel "AI received (offline fallback —
     AI-backed optimizer unavailable)" instead of the normal "AI received".
  2. State plainly in your response that the requested optimizer needs a live
     AI provider and it was down for this call, so the diff shown reflects the
     offline pipeline only, not the LLM-based optimization the user asked to see.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
