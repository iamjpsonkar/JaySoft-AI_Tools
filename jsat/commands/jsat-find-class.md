---
description: Find a class in the indexed codebase. Supports service scoping.
---

Parse $ARGUMENTS for optional --service flag, then call jsat__get_class:

  --service <name>  → scope search to one service
  (no flag)         → search entire codebase

Call jsat__get_class with name=<stripped arguments>.
Show: file, line numbers, base classes, method count, docstring.

If multiple matches: list all with file:line so the user can choose.
If no match found: suggest jsat__query(question="find class similar to <name>")

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
