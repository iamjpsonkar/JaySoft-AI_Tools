---
description: Rewrite a prompt using offline pipeline + parallel LLM agents for maximum clarity.
---

Use jsat__prompt_multi_agent with query="$ARGUMENTS" to run 3 specialist LLM agents (rewrite for clarity, context-expand to fill gaps, constraint-harden for measurable success criteria) in parallel. Show the winning rewrite with agent name and score. If the user wants just one agent, use jsat__prompt_rewrite instead.

AI-BACKEND CAUTION: both jsat__prompt_multi_agent and jsat__prompt_rewrite
require a live LLM provider for every one of their agents — there is no partial
mode where some agents run without AI. If the result is (or every agent slot
contains) "[AI unavailable...":
  1. Do NOT show that text as if it were a "winning rewrite" — an unavailable
     marker is not a rewrite and must not be presented as the scored winner.
  2. Fall back to jsat__prompt_optimize (offline, no AI dependency) with the
     same query and present that instead, explicitly labeled "offline fallback
     — multi-agent rewrite unavailable (AI backend down)".
  3. Tell the user the 3-agent (or single-agent) rewrite could not run so they
     know the result is the lighter offline pass, not the higher-quality
     LLM-scored rewrite they asked for, and suggest retrying once the AI
     provider (e.g. Ollama) is back up.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
