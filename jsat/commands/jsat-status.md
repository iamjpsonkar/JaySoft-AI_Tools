---
description: Show JSAT index statistics and health.
---

Use jsat__get_index_status and jsat__get_jsat_version to display:
- Node and edge counts with breakdown by type
- JSAT version and graph backend (SQLite / Neo4j)
- Index freshness (when last indexed)

Flag if: node count is 0 (not indexed yet), or version is outdated.
Suggest /jsat-index . if graph is empty.

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
