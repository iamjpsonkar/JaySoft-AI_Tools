---
description: Show JSAT index statistics and health.
---

Use jsat__get_index_status and jsat__get_jsat_version to display:
- Node and edge counts with breakdown by type
- JSAT version and graph backend (SQLite / Neo4j)
- Index freshness (when last indexed)

Also call jsat__health — it independently checks AI provider reachability
(`ai.is_available()` + latency), not just the graph. This is the one place a
user can proactively learn "the AI backend is down" BEFORE hitting a confusing
"[AI unavailable: ...]" result from jsat__query or another AI-dependent command
later. Always run it, not just when something else already looks broken.

Flag if:
  - node count is 0 (not indexed yet) → suggest /jsat-index .
  - jsat__health reports the AI provider unreachable → say so explicitly and
    name which AI-dependent commands (jsat__query, jsat__prompt_multi_agent,
    jsat__crack, jsat__ithinking_execute) will degrade until it's back, and
    point out that AI-free tools (jsat__blast_radius, jsat__security_review,
    jsat__get_test_gaps, jsat__list_services/endpoints, jsat__get_function/class)
    are unaffected.

Do NOT flag "version is outdated" — jsat__get_jsat_version reports only the
locally installed version; it has no access to the latest published release,
so there is no baseline to compare against. Report the version as informational
only unless the user supplies a target version to compare against explicitly.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
