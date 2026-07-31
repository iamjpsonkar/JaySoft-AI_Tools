---
description: Rewrite a prompt using offline pipeline + parallel LLM agents for maximum clarity.
---

Use jsat__prompt_multi_agent with query="$ARGUMENTS" to run 3 specialist LLM agents (rewrite for clarity, context-expand to fill gaps, constraint-harden for measurable success criteria) in parallel. Show the winning rewrite with agent name and score. If the user wants just one agent, use jsat__prompt_rewrite instead.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
