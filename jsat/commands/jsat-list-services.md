---
description: List all services found in the indexed codebase. Supports language filtering.
---

Parse $ARGUMENTS for optional --language flag, then call jsat__list_services:

  --language <lang>  → filter by language (python, go, javascript, java, ruby, rust)
  (no flag)          → list all services

Show each service with: name, language, entry point file, endpoint count.
Show total count at the end. If no services found, suggest /jsat-index .

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
