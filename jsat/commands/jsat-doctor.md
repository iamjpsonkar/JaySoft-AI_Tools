---
description: Run a full JSAT system health check.
---

Call jsat__health to run a full system check.

If the jsat__health call itself fails, times out, or the MCP tool is unreachable
(distinct from health returning a normal payload with WARN/ERROR fields inside it):
that failure IS the diagnosis, not an obstacle to one. Report:
  "❌ ERROR: MCP connection to jsat is broken — the jsat__health tool did not
  respond (<error/timeout detail>)."
Suggest: restart the Claude session / IDE integration, confirm the jsat MCP server
process is running (`jsat mcp status` if available), and re-check `claude mcp list`
or the client's MCP server config. Do not silently retry in a loop or report "all
clear" by omission — a doctor command that can't tell "healthy" from "unreachable"
is worse than useless for exactly the failures it exists to catch.

Otherwise, present results in this order:
1. JSAT version and graph backend
2. AI provider: which is active, which are available, free vs paid
3. Graph: node count, edge count, last indexed timestamp
4. MCP connection: which tools are loaded
5. Config: profile (solo/team/ci), any missing settings

Flag as ⚠️ WARN: graph not indexed, no AI configured, stale index (>7 days old)
Flag as ❌ ERROR: graph backend unavailable, AI provider failing test call
For each issue: suggest the fix command (e.g. /jsat-index ., jsat ai use ollama).

## Do not assert the index matches the current directory — verify it

"Healthy, indexed 2 hours ago" is only reassuring if the graph was built from
THIS project. jsat__health's payload is not guaranteed to expose which root path
was indexed, and a health check run from the wrong cwd (wrong repo checked out,
worktree switch, monorepo subfolder) will report a perfectly healthy index for a
DIFFERENT codebase — freshness is not the same claim as correctness for the
current directory, and conflating them is the failure mode a doctor command
exists to catch, not repeat.
  - If the health/get_index_status payload includes any indexed-path/root field,
    compare it against the current working directory (`pwd`) and flag ❌ ERROR
    "index was built from <indexed path>, not <cwd> — results below describe a
    different project" on mismatch, before reporting anything else as healthy.
  - If no such field is present in the payload, do NOT silently assume the index
    belongs to this project. State the gap plainly: "⚠️ WARN: cannot verify the
    indexed graph corresponds to <cwd> — this tool's response does not expose an
    indexed root path. If you've switched repos/worktrees since the last
    `/jsat index .`, these stats may describe a different codebase." Re-indexing
    (`/jsat index .`) is always a safe way to resolve this ambiguity.
Never present node/edge counts and "last indexed" as evidence of health for THIS
project without one of the two checks above — that gap is exactly how a stale or
foreign index gets reported as "all clear."


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
