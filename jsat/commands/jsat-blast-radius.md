---
description: Trace downstream impact of a change. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right blast-radius tool:

Supported flags:
  --file           → call jsat__blast_radius_file with path=<rest>
  --diff           → call jsat__blast_radius_diff with diff=<rest>
  --symbol         → call jsat__blast_radius_symbol with symbol=<rest>
  --severity <lvl> → filter the RESULT to breaking|degraded|warning|safe only (client-side —
                      see note below; combine freely with any of the flags above)
  --depth <N>      → override BFS depth (maps to max_depth; default 3 for the bare
                      target form, 5 for --file/--diff/--symbol — raise for a more
                      exhaustive trace, lower on a large repo to avoid a slow call)
  (no flag)        → call jsat__blast_radius with target=<rest>

NOTE ON --severity: none of jsat__blast_radius / _file / _diff / _symbol accept a
`severity_filter` parameter — that field does not exist on any of these tools.
Always call the tool with its real parameters only (target/path/diff/symbol,
max_depth, service_filter), then filter the returned impact list to the requested
severity level(s) yourself before printing. Do not pass severity_filter as a tool
argument — it will be silently ignored or rejected depending on the MCP client.
The "impacts > 5 → show Mermaid diagram" rule below is evaluated on the impact list
AFTER this client-side severity filtering, not the tool's raw unfiltered count — a
call that returns 40 raw impacts but only 2 matching `--severity breaking` should
NOT render a diagram sized for 40 nodes; render it for the 2 that are actually being
shown, or skip the diagram if the filtered count is <=5.

NOTE ON COMBINING SELECTOR FLAGS: --file, --diff, and --symbol select which
underlying tool to call and are mutually exclusive — they operate on different
input shapes (a path, a diff blob, a symbol name) and cannot be combined into one
call. If more than one is present in $ARGUMENTS, do not silently pick one: stop and
ask the user which single target form they mean. --severity and --depth are
modifiers and may be combined with exactly one selector flag (or with the bare
no-flag form).

NOT-FOUND / EMPTY-GRAPH HANDLING: if the target/path/symbol does not resolve in the
graph (empty result, or an explicit not-found error from the tool), do not report
"0 breaking / 0 degraded / ... — looks safe" — that reads as a clean bill of health
when the real situation is "this wasn't found, the graph may be stale, or the name
is wrong." Report the not-found condition explicitly and suggest jsat__get_index_status
(graph may need `jsat index .`) or a name/path correction before treating the result
as a safety signal.

Examples:
  /jsat-blast-radius src/payment/service.py
    → jsat__blast_radius(target="src/payment/service.py")

  /jsat-blast-radius --file src/payment/service.py
    → jsat__blast_radius_file(path="src/payment/service.py")

  /jsat-blast-radius --symbol PaymentService.process
    → jsat__blast_radius_symbol(symbol="PaymentService.process")

  /jsat-blast-radius --severity breaking src/payment/service.py
    → jsat__blast_radius(target="src/payment/service.py"), then keep only
      impacts where severity == "breaking" before printing

LARGE-DIFF STRATEGY: --diff hands the whole diff text to jsat__blast_radius_diff in
one call. For a diff touching more than ~30 files, or too large to paste in one
call, split by top-level directory/service and run --diff once per chunk instead —
same pattern /jsat-merge and /jsat-upgrade-impact use for large changes — then merge
the severity counts before printing the summary.

LARGE-RESULT STRATEGY for --file/--symbol/bare-target: this same blow-up risk exists
on the OUTPUT side too, not just the --diff input side — a highly-shared file or a
core utility symbol (e.g. a base `request()` helper or a shared `config` module) can
have a fan-in deep enough that a full traversal returns hundreds of impacts or times
out entirely. If the call comes back `_slow`/`_hard_timeout`, or an early partial
result already shows breadth beyond what's readable: retry with a lower --depth (2,
then 1) before giving up, and when reporting, state the depth actually used — a
"12 breaking impacts" summary at depth 1 is not the same claim as depth 5 and must
not be presented as if it were the full picture.

Group results by severity: breaking / degraded / warning / safe.
Show summary counts first. Show Mermaid diagram if impacts > 5.


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
