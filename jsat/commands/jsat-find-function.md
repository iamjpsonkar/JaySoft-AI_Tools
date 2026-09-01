---
description: Find a function or method in the indexed codebase. Supports service scoping.
---

Parse $ARGUMENTS for optional --service flag, then call jsat__get_function:

  --service <name>  → scope search to one service
  (no flag)         → search entire codebase

NOTE ON --service: jsat__get_function only accepts `name`, `file`, and `line` — it
has NO service parameter. --service cannot be forwarded to the tool call directly;
passing it and expecting server-side filtering is a no-op that silently returns
unscoped, whole-codebase results. Implement the scoping yourself:
  1. Call jsat__get_function(name=<stripped arguments, with --service removed>).
  2. If --service was given and the result has multiple matches (or a `file` field),
     call jsat__list_services() once to resolve the service name to its root path,
     then filter the matches to those whose file path falls under that root.
  3. Before treating a zero-match filter result as "no function under that service,"
     check whether --service's value even appears in the jsat__list_services()
     output. If it does not, the zero matches are a TYPO, not a true negative —
     report "no service named <service> found (closest available: <list>)" instead
     of "no function named <name> found under service <service>". Conflating
     "service doesn't exist" with "function doesn't exist under a real service"
     sends the user debugging the wrong problem.
  4. If exactly one match remains after filtering, show it. If --service filtered
     out ALL matches (and --service DID resolve to a real service), say so
     explicitly ("no function named <name> found under service <service>, but N
     match(es) exist elsewhere") rather than reporting "no match".
Show: file, line numbers, parameters (with types), return type, complexity, decorators.

If multiple matches (after any --service filtering): list all matches with file:line
so the user can choose.
If no match found: suggest jsat__query(question="find function similar to <name>")


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
