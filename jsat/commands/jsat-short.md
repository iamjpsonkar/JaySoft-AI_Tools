---
description: Ask any question — get the briefest possible correct answer (≤3 sentences).
---

Parse $ARGUMENTS for optional --one-line flag:

  --one-line  → request exactly one sentence
  (no flag)   → ≤3 sentences

Use jsat__short with question=<stripped arguments> (or jsat__query if jsat__short unavailable),
prepending the brevity constraint: "Answer in ≤3 sentences, plain language. No preamble."

NOTE: jsat__short and jsat__query both need a working LLM backend to answer —
falling back from one to the other does NOT help when the AI provider itself is
down (confirmed common failure mode: "[AI unavailable: ..."). There is no
AI-free substitute for free-form Q&A, since the entire point of this command is
an LLM-composed answer, not a graph lookup. If BOTH calls return "[AI
unavailable]": say so plainly ("AI backend unavailable — cannot answer free-form
questions right now") and suggest checking the provider (e.g. `jsat doctor`, or
whether Ollama/the configured provider is running) instead of retrying the same
failing call again or returning the raw error text as if it were the answer.

Show only the AI response — no framing, no metadata — but never show a raw
"[AI unavailable...]" string as if it were a valid ≤3-sentence answer; detect
that case and surface it as an error per the note above.
Use as a fast fallback when /jsat-query times out (not when it fails outright
due to AI-unavailable — that failure mode isn't a timeout and switching tools
won't fix it).


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
