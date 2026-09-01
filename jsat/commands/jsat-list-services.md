---
description: List all services found in the indexed codebase. Supports language filtering.
---

Parse $ARGUMENTS for optional --language flag, then call jsat__list_services:

  --language <lang>  → filter by language (python, go, javascript, java, ruby, rust)
  (no flag)          → list all services

Show each service with: name, language, entry point file, endpoint count.
Show total count at the end.

If --language <lang> was given and zero services match, distinguish the two possible
causes explicitly: (a) the repo genuinely has no services in that language — check by
also reporting the total service count across all languages so the user can tell the
filter excluded results rather than the index being empty; vs (b) the index itself is
empty/stale — in that case (total count is also 0), suggest `jsat index .`.

This tool is pure graph lookup (no LLM backend involved), so it does not degrade when
an AI provider is down — no fallback needed here.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
