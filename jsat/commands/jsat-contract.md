---
description: Check API contract compatibility between branches.
---

Parse $ARGUMENTS, then call jsat__get_api_diff:

Usage:
  (no args)            → jsat__get_api_diff(base="main", head="HEAD")
  <base> <head>        → jsat__get_api_diff(base=<base>, head=<head>)
  --score              → show only the numeric compatibility score (0-100)
  --breaking           → show breaking changes only

Examples:
  /jsat-contract
    → diff main...HEAD for all OpenAPI/AsyncAPI specs in the repo

  /jsat-contract main feature/new-payments
    → jsat__get_api_diff(base="main", head="feature/new-payments")

Show:
  - Compatibility score (100 = no breaking changes; score decays logarithmically)
  - Breaking changes: endpoint removed, required field removed, type changed
  - Non-breaking: new endpoints, optional fields added
  - Migration guide for each breaking change

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
