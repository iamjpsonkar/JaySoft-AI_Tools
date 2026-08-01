---
description: Run a security scan. Supports flags in $ARGUMENTS.
---

Parse $ARGUMENTS for optional flags, then call the right security tool:

Supported flags:
  --file <path>          → call jsat__security_scan_file with file=<path>
  --secrets              → call jsat__list_secrets to find hardcoded credentials
  --auth                 → call jsat__get_auth_coverage to show auth gaps
  --cves                 → call jsat__get_dependency_cves for CVE check
  --severity critical    → filter to critical only (pass severity_threshold="critical")
  --severity high        → filter to high+ (default: medium)
  (no flag / path only)  → call jsat__security_review with path=<rest or ".">

Examples:
  /jsat-security
    → jsat__security_review(path=".")
  /jsat-security src/payment/
    → jsat__security_review(path="src/payment/")
  /jsat-security --file src/auth/login.py
    → jsat__security_scan_file(file="src/auth/login.py")
  /jsat-security --secrets
    → jsat__list_secrets()
  /jsat-security --cves
    → jsat__get_dependency_cves()

Group findings by severity: Critical → High → Medium → Low.
For each finding: file, line, rule ID, description, remediation.

LARGE REPO STRATEGY: For repos >10k files, scan one directory at a time:
  /jsat-security src/auth/    then   /jsat-security src/payment/


BUDGET: Universal flags for every command (strip from ARGS, pass as tool args):
  timeout=<N>     → override soft budget to N seconds (default varies per tool)
  dashboard=true  → open a real-time browser dashboard for this call (closes 10s after done)
                    Example: /jsat crack dashboard=true timeout=300 redesign the auth flow
                             → jsat__crack(task='...', _budget=300, _dashboard=True)
  ⏱ progress notification = still running (wait, skip, or split — AI decides)
  ⏱ _slow in response = completed after budget (result is valid)
  ⛔ _hard_timeout in response = force-killed at 5× budget (retry with narrower scope)

HOW TO RESPOND: Actually invoke the tool(s) described above, then reply with a direct, useful answer built from the result — interpret it for the user in plain language. Do not merely describe what the tool does, and do not echo raw JSON. If a tool returns an intermediate artifact (e.g. an optimized prompt), use it to finish the task rather than presenting it as the final answer.
